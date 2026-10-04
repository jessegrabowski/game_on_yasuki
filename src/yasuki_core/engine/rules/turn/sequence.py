from dataclasses import dataclass

from dataclasses import replace

from yasuki_core.engine.rules.vocabulary.modifiers import Duration
from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId, Rulebook
from yasuki_core.engine.rules import state_based_actions, triggers
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine.rules.abilities.registry import may_stay_bowed
from yasuki_core.engine.rules.action_record import is_printed_action
from yasuki_core.engine.rules.rulebook.favor_payment import is_favor_action
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.duel.records import DuelWork
from yasuki_core.engine.rules.vocabulary.decisions import LeaveBowed
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    ApplyEffects,
    DiscardFromHand,
    DrawCard,
    RevealProvinces,
    Simultaneously,
)
from yasuki_core.engine.rules.vocabulary.game_events import (
    ActionResolved,
    EnteredPlay,
    PhaseStarted,
    Straightened,
    TurnBoundary,
)
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.interrupts import interrupt_actions
from yasuki_core.engine.rules.legality import activatable, permitted_timings, playable
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.provinces import refill_short_provinces
from yasuki_core.engine.rules.turn.structure import (
    ActionRound,
    BEGINNING_OF_ACTION_PHASE,
    Boundary,
    END_OF_ACTION_PHASE,
    END_OF_TURN,
    Moment,
    Phase,
    PHASE_TIMINGS,
    RESPONSE_TIMINGS,
    ROUNDS_OVER_HELD_WORK,
    STEP_ROUNDS,
    RoundKind,
    TURN_PHASES,
)
from yasuki_core.engine.rules.board.queries import province_zones
from yasuki_core.engine.rules.board.seats import cards_in_hand
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint, WindPrint


# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton section 1).
MAX_HAND_SIZE = 8


def next_phase(phase: Phase) -> Phase | None:
    """Return the phase that follows ``phase`` within a turn, or None after the last phase
    (Dynasty), where the turn ends with the fate draw."""
    index = TURN_PHASES.index(phase)
    return TURN_PHASES[index + 1] if index + 1 < len(TURN_PHASES) else None


# The pre-game permanents that get their enters-play effect fired as the game begins.
_PREGAME_PERMANENTS = (StrongholdPrint, SenseiPrint, WindPrint)


def begin_game(game: GameState) -> None:
    """Run the game-start pass once after ``GameState.start``, before the active player acts:
    announce each pre-game permanent entering play, then open the first turn. Re-runs on every
    replay, so those effects must be idempotent.

    The first turn is queued behind the announcement and the stack drained, so a permanent whose
    trait pauses is answered before anything straightens, and the stack is empty on return unless
    a question is open.
    """
    game.stack.append(OpenFirstTurn())
    proxies.spawn_rulebook_proxies(game)
    _begin_pregame(game)
    run_stack(game)


def _waits_beneath_its_round(game: GameState) -> bool:
    """Whether the top of the stack is held beneath the round open over it until every seat has
    passed: an action beneath its Interrupt round, a battle's After Resolution beneath the Response
    Step its resolution opened, or a duel's next step beneath a duel window."""
    top = game.stack[-1]
    held = game.round.kind is RoundKind.INTERRUPT and isinstance(top, triggers.HeldAction)
    resolving = game.round.kind is RoundKind.RESPONSE and isinstance(
        top, resolution.AfterResolution
    )
    dueling = game.round.kind is RoundKind.DUEL_WINDOW and isinstance(top, DuelWork)
    return held or resolving or dueling


def run_stack(game: GameState) -> None:
    """Drain deferred work, running each item until the stack empties or one pauses for a decision.
    A work item may itself emit a decision (setting ``pending``), so resolution stops there and
    resumes on the next :func:`~.submit`. Once the board settles, every Province standing short
    refills.
    """
    while game.stack and game.pending is None:
        if _waits_beneath_its_round(game):
            return
        game.stack.pop().resume(game)
    if game.pending is None:
        refill_short_provinces(game)


@dataclass(frozen=True, slots=True)
class OpenFirstTurn:
    """Open the first turn once the pre-game permanents have entered play and anything their entry
    asked has been answered."""

    def resume(self, game: GameState) -> None:
        _begin_turn(game)


def _begin_pregame(game: GameState) -> None:
    """Announce every pre-game permanent on the battlefield entering play as one instant, so a
    Stronghold or Sensei with an ``@on(EnteredPlay, ...)`` trigger runs it as the game begins."""
    entered = [
        EnteredPlay(card.id)
        for card in game.table.battlefield.cards
        if isinstance(card.printed, _PREGAME_PERMANENTS)
    ]
    triggers.fire_all(game, entered)


def advance(game: GameState) -> None:
    """Advance the active player's turn to the next phase. Past the Dynasty phase, run the end of
    the turn and begin the next. The gold pool empties on every phase change.

    Pause instead of finishing the turn if the end of it asks a question, as the hand-size discard
    or a delayed effect may: record the request on ``game.pending`` and return, leaving the caller
    to :func:`~.submit` a response, after which the turn finishes. Raise ``RuntimeError`` if called
    while a decision is already pending.
    """
    if game.awaiting_decision:
        raise RuntimeError("cannot advance while a decision is pending")
    game.clear_gold()
    if game.phase is Phase.ACTION:
        _lift_straighten_delays(game, END_OF_ACTION_PHASE)
    elif game.phase is Phase.BATTLE:
        resolution.end_attack_phase(game)
    ended = game.phase
    following = next_phase(ended)
    if following is not None:
        game.phase = following
        _announce_phase(game)
        # After the next phase is queued, so a question settling the board asks is answered first.
        # The last phase ends with the turn, where every record lasting for a phase lapses.
        triggers.lapse_ongoing(game, Moment(ended, Boundary.END))
        run_stack(game)
        return
    _end_turn(game)


def _announce_phase(game: GameState) -> None:
    """Queue the announcement that the current phase has begun, with its first round opening behind
    it, for the caller to drain."""
    game.stack.append(OpenRound())
    game.stack.append(triggers.AnnounceEvent(PhaseStarted(game.phase)))


def _lift_straighten_delays(game: GameState, moment: Moment) -> None:
    """Free the active seat's cards whose prohibition on straightening lifts at ``moment``, an edge
    of its Action Phase.

    Only a *later* Action Phase than the one the delay began on counts: a card bowed to pay for an
    Action is forbidden until the seat's next Action Phase, not the rest of this one. A card that
    has left the table takes its delay with it. Nothing it could be forbidden from is left.
    """
    by_id = game.table.cards_by_id
    game.straighten_delayed = {
        card_id: delay
        for card_id, delay in game.straighten_delayed.items()
        if (card := by_id.get(card_id)) is not None
        and not (delay.until == moment and card.owner is game.active and game.turn > delay.imposed)
    }


@dataclass(frozen=True, slots=True)
class LiftStraightenDelays:
    """Free the cards whose prohibition on straightening lifts at ``moment``, queued so it runs at
    that moment.

    Attributes
    ----------
    moment : Moment
        The edge of the Action Phase being reached.
    """

    moment: Moment

    def resume(self, game: GameState) -> None:
        _lift_straighten_delays(game, self.moment)


def forget_action(game: GameState) -> None:
    """Drop the record of the action last resolved, so nothing outside one is read back as one.

    A Response asks what the action it follows did. Anything still recorded across a turn or phase
    boundary is not that, and would let a Step open on an action two turns gone.
    """
    game.action_events.clear()
    game.action_resolved = False
    game.action_taken = ""
    game.action_seat = None
    game.action_targets = ()
    game.amount_declared = None
    game.options_declared = ()
    game.action_is_favor = False
    game.action = None
    game.interrupts_taken.clear()
    game.interrupts_offered = False
    game.modifications.clear()
    game.hidden_card_shown = False


def open_round(game: GameState) -> None:
    """Open the Action Round for the current phase, giving the active seat the first opportunity."""
    game.round_stack.clear()
    forget_action(game)
    game.round = ActionRound(timings=PHASE_TIMINGS[game.phase], priority=game.active)


def yield_priority(game: GameState, *, passed: bool) -> None:
    """Hand the opportunity to act to the next seat in turn order, closing the round once every seat
    has passed consecutively.

    A pass counts toward closing. Taking an action resets the count. A seat the round permits
    nothing never receives the opportunity, and counts as having passed, as does a seat holding no
    action for the open Interrupt or Response step.
    """
    if game.round.follow_ups is not None:
        # A limited additional opportunity is spent by whatever the seat did with it, so what was
        # granted for it alone goes with it.
        game.ongoing = [
            recorded
            for recorded in game.ongoing
            if recorded.duration is not Duration.FOR_ADDITIONAL_ACTION
        ]
    if not passed and game.additional_action is game.round.priority:
        # The seat keeps the opportunity, and its consecutive-pass count starts again, so a pass
        # taken at the additional opportunity does not count toward closing the round.
        game.round = replace(game.round, passes=0, follow_ups=game.additional_follow_ups)
        game.additional_action = None
        game.additional_follow_ups = None
        return
    seats = list(game.table.seats)
    passes = game.round.passes + 1 if passed else 0
    after = seats.index(game.round.priority) + 1
    for seat in seats[after:] + seats[:after]:
        if passes >= len(seats):
            break
        # Permitted-but-idle still gets asked: whether to decline a window is the seat's own call,
        # and auto-passing on its behalf is a strategy its policy owns, not a rule of the round.
        # A step is the exception: it opened only because a seat held an Interrupt or a Response,
        # and a seat holding none is a pass nobody needs to be asked for.
        if permitted_timings(game, seat) and _holds_a_step_action(game, seat):
            game.round = replace(game.round, priority=seat, passes=passes, follow_ups=None)
            return
        passes += 1
    if game.round.kind in ROUNDS_OVER_HELD_WORK:
        close_step_over_held_work(game)
        return
    if game.round.kind is RoundKind.RESPONSE:
        close_response_window(game)
        return
    if game.round.kind is RoundKind.BATTLE_SEGMENT:
        resolution.close_battle_segment(game)
        return
    advance(game)


def _end_turn(game: GameState) -> None:
    seat = game.active
    # Ending the turn is not an action, so a delayed effect resolving here has nothing to
    # interrupt and nobody to respond to.
    forget_action(game)
    # Queued beneath the delayed effects, in reverse: what happens "before the turn ends", the
    # Sincerity tokens and every trigger on the turn's end, then the rulebook's draw and the
    # discard down to the maximum hand size (CR, Drawing and Discarding Fate Cards).
    game.stack.append(EnforceMaximumHandSize(seat))
    game.stack.append(ApplyEffects((DrawCard(seat),)))
    game.stack.append(triggers.AnnounceEvent(TurnBoundary(seat, Boundary.END)))
    game.stack.append(AccrueSincerity(seat))
    triggers.resolve_delayed(game, END_OF_TURN)
    # Reached inside an action's own drain, after that drain has emptied the stack, so this nested
    # one runs only what the turn boundary queues.
    run_stack(game)


@dataclass(frozen=True, slots=True)
class AccrueSincerity:
    """Give each face-up Sincerity card in ``seat``'s Provinces a Sincerity token, all at once,
    before its turn ends (Sincerity keyword). A card recruited, discarded or refilled face-down this
    turn is not face-up in a Province, so it accrues nothing.

    Attributes
    ----------
    seat : PlayerId
        The seat whose turn is ending.
    """

    seat: PlayerId

    def resume(self, game: GameState) -> None:
        grants = [
            AdjustCounter(card.id, SINCERITY, 1)
            for _, zone in province_zones(game, self.seat)
            for card in zone.cards
            if card.face_up and keywords.SINCERITY in effective_keywords(game, card)
        ]
        triggers.resolve_effects(game, [Simultaneously(tuple(grants))])


@dataclass(frozen=True, slots=True)
class EnforceMaximumHandSize:
    """Have the seat ending its turn discard down to the maximum hand size, then begin the next
    turn.

    A work item, so what the end-of-turn draw fulfilled is offered first. The next turn is queued
    beneath the discard, so it waits for the seat's choice and for whatever the discard triggers.

    The CR makes the discard a step of the turn (Drawing and Discarding Fate Cards). It names the
    rulebook as its cause, so a card reacting to "if the action was yours" has no action to claim.

    Attributes
    ----------
    seat : PlayerId
        The seat whose turn is ending.
    """

    seat: PlayerId

    def resume(self, game: GameState) -> None:
        game.stack.append(BeginNextTurn())
        excess = len(cards_in_hand(game, self.seat)) - MAX_HAND_SIZE
        if excess > 0:
            triggers.resolve_effects(
                game, [DiscardFromHand(self.seat, excess, Rulebook.MAXIMUM_HAND_SIZE, self.seat)]
            )


@dataclass(frozen=True, slots=True)
class BeginNextTurn:
    """Begin the next turn once the end-of-turn discard, and any question it raised, has resolved.

    Pushed before the discard is announced, so a paused cascade's remainder stacks above it and
    resumes first.
    """

    def resume(self, game: GameState) -> None:
        begin_next_turn(game)


def begin_next_turn(game: GameState) -> None:
    # Ongoing records lapse here rather than with the effects held for the end of the turn, so they
    # last through its draw and discard. The turn's opening is queued beneath, in case settling the
    # board their expiry leaves asks a question.
    game.stack.append(OpenNextTurn())
    triggers.lapse_ongoing(game, END_OF_TURN)


@dataclass(frozen=True, slots=True)
class OpenNextTurn:
    """Pass the turn to the other seat and open it, once the board the last one left is settled."""

    def resume(self, game: GameState) -> None:
        triggers.resolve_effects(game, state_based_actions.dishonor_loss(game))
        if game.game_over:
            return
        game.turn += 1
        game.turn_events = ()
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
    if game.pending is not None:
        # The same shape as the end of the turn: the request set below would overwrite the paused
        # effect's question. Nothing on this path asks one today, since a win announces no event.
        raise RuntimeError("a reaction to the Honor Victory check paused the start of the turn")
    offering = may_stay_bowed(game, game.active)
    if offering:
        game.pending = LeaveBowed(seat=game.active, candidates=offering)
        return
    open_turn(game, frozenset())


def open_turn(game: GameState, staying_bowed: frozenset[str]) -> None:
    """Straighten everything but ``staying_bowed`` and whatever may not straighten yet, then queue
    the Province reveal, the turn's start, and the opening of its first round behind it for the
    caller to drain.

    The announcements are separate instants (CR), so each is its own cascade: the Province reveal,
    the turn's start, then the Action Phase's start. The round opens last, so a question asked while
    opening is answered in the previous round and hands no opportunity on. The straighten
    prohibition outlives this step: it lifts as the Action Phase this straighten precedes begins, or
    once it has ended, whichever the delay names.
    """
    _announce_phase(game)
    game.stack.append(LiftStraightenDelays(BEGINNING_OF_ACTION_PHASE))
    game.stack.append(triggers.AnnounceEvent(TurnBoundary(game.active, Boundary.BEGINNING)))
    game.stack.append(ApplyEffects((RevealProvinces(game.active),)))
    straightened = ops.straighten(
        game.table, game.active, staying_bowed | game.straighten_delayed.keys()
    )
    triggers.fire_all(game, [Straightened(card_id) for card_id in straightened])


@dataclass(frozen=True, slots=True)
class OpenRound:
    """Open the phase's first Action Round once its opening has fully resolved, forgetting what the
    opening raised: it is not an action, so it is nobody's to respond to."""

    def resume(self, game: GameState) -> None:
        open_round(game)


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1


def yield_after_action(game: GameState, acted_in: ActionRound) -> None:
    """Hand on the opportunity once an action has fully resolved. An action that paused for a
    decision has not finished, and a game that has ended has no round left to run.

    An action that opened a round of its own (a battle's Engage Segment, off the Attacker's choice
    of where to fight) hands on nothing. The new round names its own first actor, and yielding here
    would take the opportunity straight back off the Defender. A Response Step comes next when the
    action left anyone something to respond with.
    """
    if game.awaiting_decision or game.game_over:
        return
    if game.look is not None:
        # A resolver that forgot EndLook would otherwise leave every later cancel refused, by
        # either seat, for the rest of the game, with a message about cards nobody is looking at.
        raise RuntimeError("the action ended with a look still open")
    # An Interrupt bound to an effect the action never produced, a negation on the outcome of an
    # attack that then missed, is spent with the action and must not answer a Response's effect.
    # Not where the action is still resolving: the Interrupt step holds it, and a duel window is a
    # round it opened mid-resolution, so what was bound waits for it either way.
    if game.round.kind not in ROUNDS_OVER_HELD_WORK:
        game.modifications.clear()
    if game.round is not acted_in:
        return
    _announce_resolution(game)
    if game.awaiting_decision or game.game_over:
        return
    if open_response_window(game):
        return
    yield_priority(game, passed=False)


def _announce_resolution(game: GameState) -> None:
    """Announce :class:`~.ActionResolved` once for the action just resolved, before the Response
    Step, so a card in hand reading "Play after you resolve X" enters where the CR's "immediately"
    puts it. An action taken inside an Interrupt or Response step is not announced, because the
    action record names the action it answers."""
    if game.action_resolved or game.action is None or game.action_seat is None:
        return
    if game.round.kind in STEP_ROUNDS:
        return
    game.action_resolved = True
    # A resolved action is past unwinding, so what it showed cannot bar a Response's own cancel.
    game.hidden_card_shown = False
    game.ongoing = [
        recorded
        for recorded in game.ongoing
        if recorded.duration is not Duration.UNTIL_ACTION_RESOLVES
    ]
    resolved = ActionResolved(
        seat=game.action_seat,
        card_id=getattr(game.action, "card_id", None),
        favor=is_favor_action(game),
        printed=is_printed_action(game, game.action),
    )
    triggers.fire(game, resolved)


def _holds_response(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` holds a Response it could take against the action or battle just resolved,
    on a card in play or as a Strategy in hand."""
    responding = frozenset({ActionTiming.RESPONSE})
    return bool(activatable(game, seat, responding) or playable(game, seat, responding))


def _holds_a_step_action(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` holds an action the open step exists to offer. True in any other round,
    which is nobody's to hold."""
    if game.round.kind is RoundKind.INTERRUPT:
        return bool(interrupt_actions(game, seat))
    if game.round.kind is RoundKind.DUEL_WINDOW:
        # A duel that ended while its window stood open has no step left for a Response to answer,
        # so the window drains instead of offering one.
        return game.duel_being_fought is not None and _holds_response(game, seat)
    if game.round.kind is RoundKind.RESPONSE:
        return _holds_response(game, seat)
    return True


def open_response_window(game: GameState) -> bool:
    """Open the Response Step over the round the action was taken in, and report whether it opened.

    Only when a seat actually holds a Response: a step nobody could act in is a pass nobody needs to
    be asked for, and the first seat in turn order holding one acts first. Never over a game a seat
    has already won, which ends the moment it is won (CR, Setup step F). A Response is itself an
    action, and one taken inside the step opens no step of its own. The window that is already open
    is the one it belongs to. An Interrupt is not responded to either (ShE datasheet, Response):
    none opens inside the Interrupt step.
    """
    return _open_window_for_responses(game, RoundKind.RESPONSE)


def open_duel_window(game: GameState) -> bool:
    """Open a round for the Responses the duel's last step announced, over the round the duel is
    being fought in, and report whether it opened.

    The duel's remaining steps wait beneath it, so a card played here acts where the duel stands.
    This is the window Concede Defeat's "after a strike is declared, but before focused cards are
    revealed" names. It permits Responses alone, because a duel's steps are not an Action Round of
    their own and the CR gives no other designator a turn inside one.
    """
    return _open_window_for_responses(game, RoundKind.DUEL_WINDOW)


def _open_window_for_responses(game: GameState, kind: RoundKind) -> bool:
    """Open a round of ``kind`` over the open one for a seat that holds a Response, and report
    whether it opened. The first seat in turn order holding one acts first."""
    if game.game_over:
        return False
    if game.round.kind in STEP_ROUNDS:
        return False
    # Cleared before the seats are polled, not after: a card still marked from the last Step would
    # not count as a responder, and so could never open another one.
    game.responded.clear()
    order = [game.active, *(seat for seat in game.table.seats if seat is not game.active)]
    first = next((seat for seat in order if _holds_response(game, seat)), None)
    if first is None:
        return False
    game.round_stack.append(game.round)
    game.round = ActionRound(timings=RESPONSE_TIMINGS, priority=first, kind=kind)
    return True


def close_response_window(game: GameState) -> None:
    """Close the Response Step, run whatever waited beneath it, and hand the opportunity on from the
    round it suspended, unless that work paused for a decision or ended the game, where the answer
    hands it on instead."""
    game.round = game.round_stack.pop()
    # A battle's After Resolution waits beneath the step, and the step closes on a Response taken as
    # well as on a pass, which is past the point where `perform` drains the stack itself.
    run_stack(game)
    if game.awaiting_decision or game.game_over:
        return
    yield_priority(game, passed=False)


def close_step_over_held_work(game: GameState) -> None:
    """Close a step whose closing resumes the work held beneath it, once every seat has passed:
    restore the round the action was taken in, run what the step suspended, then hand the
    opportunity on from that round unless the work paused for a decision, in which case the answer
    hands it on.

    The Interrupt step holds the action it was opened over, and a duel window holds the duel's
    remaining steps. The action both belong to is still resolving, so each hands on from the round
    it suspended.
    """
    suspended = game.round_stack.pop()
    game.round = suspended
    # Read before the work runs, not after: a duel's next step opens a window of its own, and
    # `game.round` would then name that window rather than the round to hand on from, taking the
    # opportunity straight back off the seat the window just named.
    run_stack(game)
    yield_after_action(game, suspended)
