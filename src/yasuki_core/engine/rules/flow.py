from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.rules.state import GameState, Phase, TURN_PHASES
from yasuki_core.engine.rules.decisions import DiscardToHandSize, DecisionResponse

# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton §1).
MAX_HAND_SIZE = 8


def next_phase(phase: Phase) -> Phase | None:
    """Return the phase that follows ``phase`` within a turn, or None after the last phase
    (Dynasty), where the turn ends with the fate draw."""
    index = TURN_PHASES.index(phase)
    return TURN_PHASES[index + 1] if index + 1 < len(TURN_PHASES) else None


def begin_game(game: GameState) -> None:
    """Run the first turn's start-of-turn housekeeping. Call once after :meth:`GameState.start`,
    before the active player begins acting."""
    _begin_turn(game)


def advance(game: GameState) -> None:
    """Advance the active player's turn to the next phase; past the Dynasty phase, run the end of
    the turn and begin the next. The gold pool empties on every phase change.

    Pause instead of finishing the turn if the end-of-turn discard needs an answer: record the
    request on ``game.pending`` and return, leaving the caller to :func:`submit` a response before
    advancing again. Raise ``RuntimeError`` if called while a decision is already pending.
    """
    if game.awaiting_decision:
        raise RuntimeError("cannot advance while a decision is pending")
    game.clear_gold()
    following = next_phase(game.phase)
    if following is not None:
        game.phase = following
        return
    _end_turn(game)


def submit(game: GameState, response: DecisionResponse) -> None:
    """Answer the pending decision and resume the turn loop.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the answer is malformed
    or illegal against the game state.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    if not isinstance(request, DiscardToHandSize):
        raise ValueError(f"no handler for decision {type(request).__name__}")
    if not request.accepts(response):
        raise ValueError("malformed answer to the pending decision")
    _apply_discard(game, request.seat, response.choices)
    game.pending = None
    _begin_next_turn(game)


def _end_turn(game: GameState) -> None:
    seat = game.active
    ops.draw_to_hand(game.table, seat)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    excess = len(hand.cards) - MAX_HAND_SIZE
    if excess > 0:
        game.pending = DiscardToHandSize(seat, count=excess)
        return
    _begin_next_turn(game)


def _begin_next_turn(game: GameState) -> None:
    game.turn += 1
    game.active = _other(game.active)
    game.phase = Phase.ACTION
    _begin_turn(game)


def _begin_turn(game: GameState) -> None:
    ops.straighten(game.table, game.active)
    ops.reveal_provinces(game.table, game.active)


def _apply_discard(game: GameState, seat: PlayerId, card_ids: tuple[str, ...]) -> None:
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    by_id = {card.id: card for card in hand.cards}
    missing = [card_id for card_id in card_ids if card_id not in by_id]
    if missing:
        raise ValueError(f"discard names cards not in {seat.name}'s hand: {missing}")
    for card_id in card_ids:
        ops.move_card(game.table, by_id[card_id], ZoneKey(seat, ZoneRole.FATE_DISCARD))


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1
