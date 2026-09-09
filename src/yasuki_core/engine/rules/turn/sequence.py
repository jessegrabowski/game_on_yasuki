from dataclasses import replace

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import favor, state_based_actions, triggers
from yasuki_core.engine.rules.abilities.registry import may_stay_bowed
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.decisions import DiscardToHandSize, LeaveBowed
from yasuki_core.engine.rules.effects import AdjustCounter
from yasuki_core.engine.rules.events import (
    CardDiscarded,
    EnteredPlay,
    Revealed,
    Straightened,
    TurnStarted,
)
from yasuki_core.engine.rules.keyword_grants import effective_keywords
from yasuki_core.engine.rules.legality import activatable, permitted_timings
from yasuki_core.engine.rules.modifiers import Duration
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import (
    ActionRound,
    END_OF_TURN,
    Phase,
    PHASE_TIMINGS,
    RESPONSE_TIMINGS,
    RoundKind,
    TURN_PHASES,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint, WindPrint


# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton §1).
MAX_HAND_SIZE = 8


def next_phase(phase: Phase) -> Phase | None:
    """Return the phase that follows ``phase`` within a turn, or None after the last phase
    (Dynasty), where the turn ends with the fate draw."""
    index = TURN_PHASES.index(phase)
    return TURN_PHASES[index + 1] if index + 1 < len(TURN_PHASES) else None


# The pre-game permanents that get their enters-play effect fired as the game begins.
_PREGAME_PERMANENTS = (StrongholdPrint, SenseiPrint, WindPrint)


def begin_game(game: GameState) -> None:
    """Run the game-start pass once after :meth:`GameState.start`, before the active player acts:
    fire each pre-game permanent's enters-play effect, then the first turn's housekeeping. Re-runs on
    every replay, so those effects must be idempotent."""
    _begin_pregame(game)
    _begin_turn(game)


def _begin_pregame(game: GameState) -> None:
    """Fire EnteredPlay for each pre-game permanent on the battlefield, so a Stronghold or Sensei with
    an ``@on(EnteredPlay, ...)`` trigger runs it as the game begins."""
    for card in list(game.table.battlefield.cards):
        if isinstance(card.printed, _PREGAME_PERMANENTS):
            triggers.fire(game, EnteredPlay(card.id))


def advance(game: GameState) -> None:
    """Advance the active player's turn to the next phase; past the Dynasty phase, run the end of
    the turn and begin the next. The gold pool empties on every phase change.

    Pause instead of finishing the turn if the end-of-turn discard needs an answer: record the
    request on ``game.pending`` and return, leaving the caller to :func:`submit` a response before
    advancing again. That discard is the only question the end of a turn may ask — raise
    ``RuntimeError`` if a delayed effect asks one of its own, and if called while a decision is
    already pending.
    """
    if game.awaiting_decision:
        raise RuntimeError("cannot advance while a decision is pending")
    game.clear_gold()
    if game.phase is Phase.ACTION:
        _lift_straighten_delays(game)
    elif game.phase is Phase.BATTLE:
        resolution.end_attack_phase(game)
    following = next_phase(game.phase)
    if following is not None:
        game.phase = following
        open_round(game)
        return
    _end_turn(game)


def _lift_straighten_delays(game: GameState) -> None:
    """Free the active seat's cards that were forbidden to straighten, now its Action Phase is over.

    Only a *later* Action Phase than the one the delay began on counts: a card bowed to pay for an
    Action is forbidden until the seat's next Action Phase, not the rest of this one. A card that has
    left the table takes its delay with it — nothing it could be forbidden from is left.
    """
    by_id = game.table.cards_by_id
    game.straighten_delayed = {
        card_id: imposed
        for card_id, imposed in game.straighten_delayed.items()
        if (card := by_id.get(card_id)) is not None
        and not (card.owner is game.active and game.turn > imposed)
    }


def forget_action(game: GameState) -> None:
    """Drop the record of the action last resolved, so nothing outside one is read back as one.

    A Response asks what the action it follows did. Anything still recorded across a turn or phase
    boundary is not that, and would let a Step open on an action two turns gone.
    """
    game.action_events.clear()
    game.action_taken = ""
    game.action_is_favor = False
    game.action = None


def open_round(game: GameState) -> None:
    """Open the Action Round for the current phase, giving the active seat the first opportunity."""
    game.round_stack.clear()
    forget_action(game)
    game.round = ActionRound(timings=PHASE_TIMINGS[game.phase], priority=game.active)


def yield_priority(game: GameState, *, passed: bool) -> None:
    """Hand the opportunity to act to the next seat in turn order, closing the round once every seat
    has passed consecutively.

    A pass counts toward closing; taking an action resets the count. A seat the round permits nothing
    never receives the opportunity, and counts as having passed.
    """
    seats = list(game.table.seats)
    passes = game.round.passes + 1 if passed else 0
    after = seats.index(game.round.priority) + 1
    for seat in seats[after:] + seats[:after]:
        if passes >= len(seats):
            break
        # Permitted-but-idle still gets asked: whether to decline a window is the seat's own call,
        # and auto-passing on its behalf is a strategy its policy owns, not a rule of the round.
        if permitted_timings(game, seat):
            game.round = replace(game.round, priority=seat, passes=passes)
            return
        passes += 1
    if game.round.kind is RoundKind.RESPONSE:
        close_response_window(game)
        return
    if game.round.kind is RoundKind.BATTLE_SEGMENT:
        resolution.close_battle_segment(game)
        return
    advance(game)


def _end_turn(game: GameState) -> None:
    seat = game.active
    triggers.resolve_delayed(game, END_OF_TURN)
    if game.pending is not None:
        # What is left of the end of the turn — Sincerity, the fate draw, the hand-size discard —
        # has nowhere to resume from, and setting the discard request would strand the paused
        # effect's own cascade behind it. Nothing delayed today asks a question.
        raise RuntimeError("a delayed effect paused the end of the turn, which cannot resume")
    _accrue_sincerity(game, seat)
    ops.draw_to_hand(game.table, seat)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    # A rulebook proxy is not a card, so it neither counts toward the limit nor can be discarded to
    # meet it.
    held = [card for card in hand.cards if not favor.is_rulebook_proxy(card)]
    excess = len(held) - MAX_HAND_SIZE
    if excess > 0:
        candidates = tuple(card.id for card in held)
        game.pending = DiscardToHandSize(seat, candidates, count=excess)
        return
    begin_next_turn(game)


def _accrue_sincerity(game: GameState, seat: PlayerId) -> None:
    """Before ``seat``'s turn ends, give each face-up Sincerity card lingering in its Provinces a
    Sincerity token. A card that flushed (was recruited or discarded) or arrived face-down as a
    refill this turn is not face-up in a Province, so it does not accrue."""
    grants = [
        AdjustCounter(card.id, SINCERITY, 1)
        for key, zone in game.table.zones.items()
        if key.owner is seat and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if card.face_up and keywords.SINCERITY in effective_keywords(game, card)
    ]
    triggers.resolve_effects(game, grants)


def begin_next_turn(game: GameState) -> None:
    # Drop until-end-of-turn modifiers as the turn ends; the comprehension keeps creation order so
    # the list rebuilds identically under replay.
    game.modifiers = [m for m in game.modifiers if m.duration is not Duration.UNTIL_END_OF_TURN]
    # Modifiers expiring can make the board illegal on their own, with no effect committing and so
    # no cascade to catch it. Settle that before the new turn starts and anything reads the board.
    triggers.enforce_state_based_actions(game)
    triggers.resolve_effects(game, state_based_actions.dishonor_loss(game))
    if game.game_over:
        return
    game.turn += 1
    game.active = _other(game.active)
    game.phase = Phase.ACTION
    _begin_turn(game)


def _begin_turn(game: GameState) -> None:
    """Open the turn: straighten, reveal the Provinces, and announce that the turn has begun.

    An Honor Victory is checked before any of it: the CR wins the game on the Honor the seat starts
    the turn with, so nothing the opening does can be what pushes it over. A card that may remain
    bowed is asked about next, since that is a choice its controller makes before each straightening
    (CR, May Remain Bowed). Pausing there leaves the rest of the turn's opening for the submit that
    answers.
    """
    triggers.resolve_effects(game, state_based_actions.honor_victory(game))
    if game.game_over:
        return
    open_round(game)
    offering = may_stay_bowed(game, game.active)
    if offering:
        game.pending = LeaveBowed(seat=game.active, candidates=offering)
        return
    open_turn(game, frozenset())


def open_turn(game: GameState, staying_bowed: frozenset[str]) -> None:
    """Straighten everything but ``staying_bowed`` and whatever may not straighten yet, reveal the
    Provinces, and open the turn.

    The prohibition outlives this step — it lifts when the Action Phase this straighten precedes has
    ended — so nothing is spent here.
    """
    straightened = ops.straighten(
        game.table, game.active, staying_bowed | game.straighten_delayed.keys()
    )
    for card_id in straightened:
        triggers.fire(game, Straightened(card_id))
    for card_id in ops.reveal_provinces(game.table, game.active):
        triggers.fire(game, Revealed(card_id))
    triggers.fire(game, TurnStarted(game.active))
    # Opening the turn is not an action, so what it just raised is nobody's to respond to.
    forget_action(game)


def apply_discard(game: GameState, seat: PlayerId, card_ids: tuple[str, ...]) -> None:
    """Discard down to the maximum hand size at the end of the turn.

    The rulebook trims the hand, so the discard names no seat as its cause: it is a step of the turn
    rather than an action (CR, Drawing and Discarding Fate Cards), and a card reacting to "if the
    action was yours" has no action to claim.
    """
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    by_id = {card.id: card for card in hand.cards}
    missing = [card_id for card_id in card_ids if card_id not in by_id]
    if missing:
        raise ValueError(f"discard names cards not in {seat.name}'s hand: {missing}")
    for card_id in card_ids:
        card = by_id[card_id]
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FATE_DISCARD))
        triggers.fire(
            game,
            CardDiscarded(card_id, card.side, Rulebook.MAXIMUM_HAND_SIZE, from_hand_or_deck=True),
        )


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1


def yield_after_action(game: GameState, acted_in: ActionRound) -> None:
    """Hand on the opportunity once an action has fully resolved. An action that paused for a
    decision has not finished, and a game that has ended has no round left to run.

    An action that opened a round of its own — a battle's Engage Segment, off the Attacker's choice
    of where to fight — hands on nothing: the new round names its own first actor, and yielding here
    would take the opportunity straight back off the Defender. A Response Step comes next when the
    action left anyone something to respond with.
    """
    if game.awaiting_decision or game.game_over:
        return
    if game.round is not acted_in:
        return
    if open_response_window(game):
        return
    yield_priority(game, passed=False)


def _responders(game: GameState) -> list[PlayerId]:
    """Every seat holding a Response it could take against the action just resolved."""
    responding = frozenset({ActionTiming.RESPONSE})
    return [seat for seat in game.table.seats if activatable(game, seat, responding)]


def open_response_window(game: GameState) -> bool:
    """Open the Response Step over the round the action was taken in, and report whether it opened.

    Only when a seat actually holds a Response: a step nobody could act in is a pass nobody needs to
    be asked for. A Response is itself an action, and one taken inside the step opens no step of its
    own — the window that is already open is the one it belongs to.
    """
    if game.round.kind is RoundKind.RESPONSE:
        return False
    # Cleared before the seats are polled, not after: a card still marked from the last Step would
    # not count as a responder, and so could never open another one.
    game.responded.clear()
    if not _responders(game):
        return False
    game.round_stack.append(game.round)
    game.round = ActionRound(
        timings=RESPONSE_TIMINGS, priority=game.active, kind=RoundKind.RESPONSE
    )
    return True


def close_response_window(game: GameState) -> None:
    """Close the Response Step and hand the opportunity on from the round it suspended."""
    game.round = game.round_stack.pop()
    yield_priority(game, passed=False)
