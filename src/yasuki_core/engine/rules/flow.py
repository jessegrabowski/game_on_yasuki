from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, DeckKey, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.pregame import StrongholdCard
from yasuki_core.engine.rules.actions import Action, DynastyDiscard, Legacy, Pass, Recruit
from yasuki_core.engine.rules.state import GameState, Phase, TURN_PHASES
from yasuki_core.engine.rules.work import ResolveRecruit, WorkItem
from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseLegacyCard,
    ChoosePayment,
    DiscardToHandSize,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.effects import effective_gold_production
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.events import CardDiscarded, EnteredPlay, TurnStarted

# The boldface keyword marking a card the Legacy rulebook ability can search out.
LEGACY_KEYWORD = "Legacy"

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
        case DynastyDiscard(card_id=card_id):
            dynasty_discard(game, card_id)
        case Legacy():
            legacy(game)


def produce_gold(game: GameState, card_id: str, amount: int) -> None:
    """Bow the card and add ``amount`` gold to its owner's pool — the yield the payment offer quoted
    for it (KD6). Gold is only produced while paying a cost (rules-skeleton §7), so a payment drives
    this."""
    card = game.table.cards_by_id[card_id]
    card.bow()
    game.add_gold(card.owner, amount)


def gold_producers(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The unbowed gold producers ``seat`` controls in play — its Stronghold and gold Holdings —
    each a source it may bow for gold (KD6, stat-derived)."""
    return [
        card
        for card in game.table.battlefield.cards
        if card.owner is seat and not card.bowed and effective_gold_production(game, card) > 0
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
        produced=tuple(
            (producer.id, effective_gold_production(game, producer, targets=(card,)))
            for producer in producers
        ),
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
        case BanishForLegacy():
            _apply_legacy_banish(game, request, response)
        case ChooseLegacyCard():
            _apply_legacy_choice(game, request, response)
        case PlaceLegacy():
            _apply_legacy_placement(game, request, response)
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
    produced = dict(request.produced)
    for card_id in response.choices:
        produce_gold(game, card_id, produced[card_id])
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
    triggers.fire(game, EnteredPlay(card_id))


def dynasty_discard(game: GameState, card_id: str) -> None:
    """Discard a face-up province card to its owner's dynasty discard and refill the province — the
    Dynasty Discard action. It has no cost, so it resolves at once with no payment."""
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    province = _province_of(game, seat, card_id)
    ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    if province is not None:
        ops.fill_province(game.table, seat, province)
    triggers.fire(game, CardDiscarded(card_id, card.side, seat))


def legacy_key(seat: PlayerId, turn: int) -> str:
    """The once-per-turn usage key for a seat's Legacy ability, scoped to the turn so it resets each
    turn without clearing ``GameState.once_per``."""
    return f"legacy:{seat.name}:{turn}"


def is_legacy_card(card: L5RCard) -> bool:
    """Whether ``card`` carries the Legacy keyword, so the Legacy ability can search it out."""
    return any(keyword.lower() == LEGACY_KEYWORD.lower() for keyword in card.keywords)


def legacy_candidates(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Legacy cards ``seat`` could find right now — those in its dynasty deck or its provinces.
    Empty means a Legacy search would whiff and lose the game."""
    found = [
        card for card in game.table.decks[DeckKey(seat, Side.DYNASTY)].cards if is_legacy_card(card)
    ]
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            found.extend(card for card in zone.cards if is_legacy_card(card))
    return found


def legacy(game: GameState) -> None:
    """Announce the Legacy ability: claim its once-per-turn use and pause for the banish cost. The
    search and placement follow once the banished card is chosen."""
    seat = game.active
    game.use_once(legacy_key(seat, game.turn))
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    game.pending = BanishForLegacy(seat=seat, candidates=tuple(card.id for card in hand.cards))


def _apply_legacy_banish(
    game: GameState, request: BanishForLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    banished = game.table.cards_by_id[response.choices[0]]
    ops.move_card(game.table, banished, ZoneKey(seat, ZoneRole.FATE_BANISH))
    game.pending = None
    found = legacy_candidates(game, seat)
    if not found:
        game.loser = seat  # the whiff: failing to find a Legacy card loses the game
        return
    game.pending = ChooseLegacyCard(seat=seat, candidates=tuple(card.id for card in found))


def _apply_legacy_choice(
    game: GameState, request: ChooseLegacyCard, response: DecisionResponse
) -> None:
    seat = request.seat
    legacy_card = game.table.cards_by_id[response.choices[0]]
    game.pending = None
    provinces = _displaceable_provinces(game, seat, keep=legacy_card.id)
    if not provinces:
        # No province to sacrifice — only reachable at zero provinces (a military loss the engine
        # does not model yet). Reveal the found card where it sits rather than placing it.
        legacy_card.turn_face_up()
        return
    game.pending = PlaceLegacy(seat=seat, candidates=provinces, legacy_card_id=legacy_card.id)


def _apply_legacy_placement(
    game: GameState, request: PlaceLegacy, response: DecisionResponse
) -> None:
    seat = request.seat
    displaced = game.table.cards_by_id[response.choices[0]]
    legacy_card = game.table.cards_by_id[request.legacy_card_id]
    target_key = _province_key_of(game, seat, displaced.id)
    source_zone = _province_of(game, seat, legacy_card.id)  # None when it came from the deck
    ops.move_card(game.table, displaced, ZoneKey(seat, ZoneRole.DYNASTY_DISCARD))
    ops.move_card(game.table, legacy_card, target_key)
    legacy_card.turn_face_up()  # a placed Legacy card enters its province revealed
    game.pending = None
    if source_zone is None:
        game.table.decks[DeckKey(seat, Side.DYNASTY)].shuffle(seed=game.seed + game.turn)
    else:
        ops.fill_province(game.table, seat, source_zone)
    triggers.fire(game, CardDiscarded(displaced.id, displaced.side, seat))


def _displaceable_provinces(game: GameState, seat: PlayerId, *, keep: str) -> tuple[str, ...]:
    """The province cards ``seat`` may discard to make room for a placed Legacy card — its face card
    in each province, skipping the province that already holds the found card (id ``keep``), which
    cannot be its own sacrifice."""
    displaceable: list[str] = []
    for key, zone in game.table.zones.items():
        if key.owner is not seat or key.role is not ZoneRole.PROVINCE or not zone.cards:
            continue
        if any(card.id == keep for card in zone.cards):
            continue
        displaceable.append(zone.cards[-1].id)
    return tuple(displaceable)


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
    triggers.fire(game, TurnStarted(game.active))


def _apply_discard(game: GameState, seat: PlayerId, card_ids: tuple[str, ...]) -> None:
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    by_id = {card.id: card for card in hand.cards}
    missing = [card_id for card_id in card_ids if card_id not in by_id]
    if missing:
        raise ValueError(f"discard names cards not in {seat.name}'s hand: {missing}")
    for card_id in card_ids:
        card = by_id[card_id]
        ops.move_card(game.table, card, ZoneKey(seat, ZoneRole.FATE_DISCARD))
        triggers.fire(game, CardDiscarded(card_id, card.side, seat))


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


def _province_key_of(game: GameState, seat: PlayerId, card_id: str) -> ZoneKey:
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            if any(card.id == card_id for card in zone.cards):
                return key
    raise ValueError(f"no province of {seat.name} holds card {card_id}")


def _other(seat: PlayerId) -> PlayerId:
    return PlayerId.P2 if seat is PlayerId.P1 else PlayerId.P1
