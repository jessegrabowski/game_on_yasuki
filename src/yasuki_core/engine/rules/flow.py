from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.engine.rules.actions import Action, Pass, Recruit
from yasuki_core.engine.rules.state import GameState, Phase, TURN_PHASES
from yasuki_core.engine.rules.work import ResolveRecruit, WorkItem
from yasuki_core.engine.rules.decisions import ChoosePayment, DiscardToHandSize, DecisionResponse

# The default maximum hand size, enforced by the end-of-turn discard (rules-skeleton §1).
MAX_HAND_SIZE = 8

# Extra gold a Recruit costs when the card's clan differs from the recruiting seat's (rules-skeleton
# §6: "+2 Gold if its clan ≠ yours").
OFF_CLAN_SURCHARGE = 2


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


def perform(game: GameState, action: Action) -> None:
    """Apply a chosen action: pass to end the phase, or recruit a card from a province. The single
    action-apply dispatch, mirroring :func:`submit` for decisions."""
    match action:
        case Pass():
            advance(game)
        case Recruit(card_id=card_id):
            recruit(game, card_id)


def produce_gold(game: GameState, card_id: str) -> None:
    """Bow the card and add its ``gold_production`` to its owner's pool (KD6, stat-derived). Gold is
    only produced while paying a cost (rules-skeleton §7), so a payment drives this."""
    card = game.table.cards_by_id[card_id]
    card.bow()
    game.add_gold(card.owner, card.gold_production)


def gold_producers(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The unbowed gold producers ``seat`` controls in play — its Stronghold and gold Holdings —
    each a source it may bow for gold (KD6, stat-derived)."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat and not card.bowed and getattr(card, "gold_production", 0) > 0
    ]


def recruit_cost(game: GameState, card: L5RCard) -> int:
    """The gold a seat pays to recruit ``card``: its printed gold cost, plus the off-clan surcharge
    when the card's clan differs from the seat's Stronghold clan (rules-skeleton §6)."""
    cost = card.gold_cost or 0
    seat_clan = _seat_clan(game, card.owner)
    if card.clan is not None and seat_clan is not None and card.clan != seat_clan:
        cost += OFF_CLAN_SURCHARGE
    return cost


def recruit(game: GameState, card_id: str) -> None:
    """Announce a Recruit: defer bringing the card into play, then pause for its cost payment. The
    payment bows gold producers to cover :func:`recruit_cost`; once answered, the stack resolves the
    move into play and the province refill."""
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    producers = gold_producers(game, seat)
    game.stack.append(ResolveRecruit(seat, card_id))
    game.pending = ChoosePayment(
        seat=seat,
        candidates=tuple(producer.id for producer in producers),
        amount=recruit_cost(game, card),
        available=game.gold[seat],
        produced=tuple((producer.id, producer.gold_production) for producer in producers),
        label=card.name,
    )


def submit(game: GameState, response: DecisionResponse) -> None:
    """Answer the pending decision and resume the engine.

    Dispatch on the request type to its apply-handler, then continue: an end-of-turn discard begins
    the next turn, while a cost payment drains the stack to finish the action that paused for it.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the answer is malformed
    or illegal against the game state.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    if not request.accepts(response):
        raise ValueError("malformed answer to the pending decision")
    match request:
        case DiscardToHandSize():
            _apply_discard(game, request.seat, response.choices)
            game.pending = None
            _begin_next_turn(game)
        case ChoosePayment():
            _apply_payment(game, request, response)
            game.pending = None
            run_stack(game)
        case _:
            raise ValueError(f"no handler for decision {type(request).__name__}")


def cancel(game: GameState) -> None:
    """Back out of the pending decision, undoing the action that raised it.

    Only a Recruit's payment is cancellable: nothing is committed until it is answered — no gold
    spent, no producer bowed, the card still in its province — so dropping the decision and its
    deferred :class:`ResolveRecruit` restores the pre-announce state.

    Raise ``RuntimeError`` if no decision is pending, or ``ValueError`` if the pending decision
    cannot be cancelled.
    """
    request = game.pending
    if request is None:
        raise RuntimeError("no decision is pending")
    match request:
        case ChoosePayment():
            _cancel_recruit_payment(game)
        case _:
            raise ValueError(f"{type(request).__name__} cannot be cancelled")


def _cancel_recruit_payment(game: GameState) -> None:
    if not game.stack or not isinstance(game.stack[-1], ResolveRecruit):
        raise ValueError("the pending payment has no recruit to undo")
    game.stack.pop()
    game.pending = None


def run_stack(game: GameState) -> None:
    """Drain deferred work, running each item until the stack empties or one pauses for a decision.
    A work item may itself emit a decision (setting ``pending``), so resolution stops there and
    resumes on the next :func:`submit`."""
    while game.stack and game.pending is None:
        _resolve(game, game.stack.pop())


def _resolve(game: GameState, item: WorkItem) -> None:
    match item:
        case ResolveRecruit(seat=seat, card_id=card_id):
            _resolve_recruit(game, seat, card_id)
        case _:
            raise ValueError(f"no resolver for work item {type(item).__name__}")


def _apply_payment(game: GameState, request: ChoosePayment, response: DecisionResponse) -> None:
    for card_id in response.choices:
        produce_gold(game, card_id)
    game.spend_gold(request.seat, request.amount)


def _resolve_recruit(game: GameState, seat: PlayerId, card_id: str) -> None:
    card = game.table.cards_by_id[card_id]
    province = _province_of(game, seat, card_id)
    # Enter unplaced so the client clusters the new holding into the seat's home row by the
    # stronghold, rather than dropping it at the origin.
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    card.bow()  # Holdings enter play bowed (rules-skeleton §6)
    if province is not None:
        ops.fill_province(game.table, seat, province)


def _end_turn(game: GameState) -> None:
    seat = game.active
    ops.draw_to_hand(game.table, seat)
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    excess = len(hand.cards) - MAX_HAND_SIZE
    if excess > 0:
        candidates = tuple(card.id for card in hand.cards)
        game.pending = DiscardToHandSize(seat, candidates, count=excess)
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


def _seat_clan(game: GameState, seat: PlayerId) -> str | None:
    for card in game.table.battlefield.cards:
        if card.owner is seat and isinstance(card, StrongholdCard):
            return card.clan
    return None


def _province_of(game: GameState, seat: PlayerId, card_id: str) -> ProvinceZone | None:
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            if any(card.id == card_id for card in zone.cards):
                return zone
    return None


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1
