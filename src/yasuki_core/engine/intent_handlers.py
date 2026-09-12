from numpy.random import default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, RULEBOOK_PROXY_IDS, Side
from yasuki_core.engine import ops
from yasuki_core.engine.redaction import card_identity_public
from yasuki_core.engine.table import (
    BATTLEFIELD,
    UNPLACED_BOARD_POS,
    AttachTarget,
    DeckKey,
    MoveDest,
    TableState,
    ZoneKey,
    ZoneRole,
    owns_card,
    owns_deck,
    owns_zone,
    zone_accepts,
    zone_owned_by_card,
)
from yasuki_core.engine.intents import (
    AdjustCounter,
    Attach,
    CardFlagIntent,
    CreateProvince,
    DestroyProvince,
    Detach,
    DiscardProvince,
    Draw,
    Event,
    FillProvince,
    FlipCoin,
    FlipDeckTop,
    GiveControl,
    Intent,
    IntentOp,
    MoveCard,
    MoveDeckTop,
    Peek,
    Raise,
    RemoveCard,
    ReorderHand,
    ReorderPile,
    RollDice,
    SearchDeck,
    SetCardPos,
    SetCardPositions,
    SetHonor,
    SetNote,
    Show,
    Shuffle,
    SpawnCard,
    Unpeek,
    Unshow,
)


def _move_card(state: TableState, seat: PlayerId, intent: MoveCard) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    dest = intent.to

    if dest == BATTLEFIELD:
        ops.move_card(state, card, BATTLEFIELD, position=intent.position)
        if intent.face_down:
            # A card laid face down is a back to everyone, its owner included; peeking it back keeps
            # the player able to read their own focused card while the opponent sees only a back.
            card.turn_face_down()
            card.add_peeker(seat)
        state.seq += 1
        pos = state.positions[card.id]
        return [
            Event(
                state.seq,
                seat,
                MoveCard(card.id, BATTLEFIELD, pos, face_down=intent.face_down),
                (card.id,),
            )
        ]

    if isinstance(dest, DeckKey):
        if not owns_deck(state, seat, dest) or dest.side is not card.side:
            return []
        ops.move_card(state, card, dest, to_bottom=intent.to_bottom)
        state.seq += 1
        return [
            Event(state.seq, seat, MoveCard(card.id, dest, to_bottom=intent.to_bottom), (card.id,))
        ]

    zone = state.zones.get(dest)
    if (
        zone is None
        or not owns_zone(state, seat, dest)
        or not zone_owned_by_card(zone, card)
        or not zone_accepts(zone, card)
    ):
        return []
    # Dropping a card onto the zone it already occupies changes nothing, so it produces no event.
    if not ops.move_card(state, card, dest, index=intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest), (card.id,))]


def _move_deck_top(state: TableState, seat: PlayerId, intent: MoveDeckTop) -> list[Event]:
    # Source the deck's top card, then route it exactly like a MoveCard, since the deck owner alone
    # may do this, and the card carries the owner's id so the delegated ownership gate passes.
    if not owns_deck(state, seat, intent.deck):
        return []
    cards = state.decks[intent.deck].cards
    if not cards:
        return []
    return _move_card(state, seat, MoveCard(cards[-1].id, intent.to, intent.position))


def _set_card_pos(state: TableState, seat: PlayerId, intent: SetCardPos) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    if not any(held is card for held in state.battlefield.cards):
        return []
    if not ops.set_position(state, card, intent.x, intent.y):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _set_card_positions(state: TableState, seat: PlayerId, intent: SetCardPositions) -> list[Event]:
    changed = []
    for card_id, x, y in intent.moves:
        card = state.cards_by_id.get(card_id)
        if card is None or not owns_card(state, seat, card_id):
            continue
        if not any(held is card for held in state.battlefield.cards):
            continue
        if ops.set_position(state, card, x, y):
            changed.append(card.id)
    if not changed:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, tuple(changed))]


def _reorder_hand(state: TableState, seat: PlayerId, intent: ReorderHand) -> list[Event]:
    if not ops.reorder_in_hand(state, seat, intent.card_id, intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _reorder_pile(state: TableState, seat: PlayerId, intent: ReorderPile) -> list[Event]:
    if getattr(intent.pile, "owner", None) != seat:
        return []
    if not ops.reorder_in_pile(state, intent.pile, intent.card_id, intent.index):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _raise(state: TableState, seat: PlayerId, intent: Raise) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    cards = state.battlefield.cards
    if not cards or cards[-1] is card or not any(held is card for held in cards):
        return []
    ops.bring_to_top(state, card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _set_note(state: TableState, seat: PlayerId, intent: SetNote) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not card.face_up:
        return []
    note = (intent.note or "").strip() or None
    if note == card.note:
        return []
    card.set_note(note)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _adjust_counter(state: TableState, seat: PlayerId, intent: AdjustCounter) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not card.face_up:
        return []
    key = intent.counter.key
    before = card.counters.get(key, 0)
    # adjust_counter floors at zero; a floored no-op emits nothing.
    after = max(0, before + intent.delta)
    if after == before:
        return []
    card.adjust_counter(key, intent.delta)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _give_control(state: TableState, seat: PlayerId, intent: GiveControl) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    # Only the controller may give a face-up card away, matching the client gate.
    if card is None or not card.face_up or card.owner != seat:
        return []
    # Only a card on the shared battlefield may change hands; reassigning one held in an owned zone
    # (hand, deck, province) would break the zone/owner invariant the table validates.
    if not any(held is card for held in state.battlefield.cards):
        return []
    opponent = next((other for other in state.seats if other != seat), None)
    if opponent is None:
        return []
    card.set_owner(opponent)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _bow_card(card: L5RCard) -> bool:
    if card.bowed:
        return False
    card.bow()
    return True


def _unbow_card(card: L5RCard) -> bool:
    if not card.bowed:
        return False
    card.unbow()
    return True


def _flip_card(card: L5RCard) -> bool:
    # Turning the card over consumes any private peek: flipping it face up makes it public, and
    # flipping it back down must yield a genuine back, not one its former peekers still read.
    card.flip()
    card.clear_peekers()
    return True


def _flip_face_card(card: L5RCard) -> bool:
    if card.back_card_id is None:
        return False
    card.flip_face()
    return True


def _invert_card(card: L5RCard) -> bool:
    if card.inverted:
        card.uninvert()
    else:
        card.invert()
    return True


_FLAG_MUTATORS = {
    IntentOp.BOW: _bow_card,
    IntentOp.UNBOW: _unbow_card,
    IntentOp.FLIP: _flip_card,
    IntentOp.FLIP_FACE: _flip_face_card,
    IntentOp.INVERT: _invert_card,
}


def _apply_flag(state: TableState, seat: PlayerId, intent: CardFlagIntent) -> list[Event]:
    # Atomic: reject the whole batch unless every target is known and owned.
    cards = []
    for card_id in intent.card_ids:
        if not owns_card(state, seat, card_id):
            return []
        cards.append(state.cards_by_id[card_id])
    mutate = _FLAG_MUTATORS[intent.op]
    changed = tuple(card.id for card in cards if mutate(card))
    if not changed:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, changed)]


def _show(state: TableState, seat: PlayerId, intent: Show) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or card.shown:
        return []
    card.show()
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _unshow(state: TableState, seat: PlayerId, intent: Unshow) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or not card.shown:
        return []
    card.unshow()
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _peek(state: TableState, seat: PlayerId, intent: Peek) -> list[Event]:
    # Owner-gated: you may privately peek only your own (or an owner-less public) hidden card.
    # Seeing a card the opponent holds requires them to Show it; you cannot reach across and look
    # yourself.
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id) or seat in card.peekers:
        return []
    card.add_peeker(seat)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _unpeek(state: TableState, seat: PlayerId, intent: Unpeek) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or seat not in card.peekers:
        return []
    card.remove_peeker(seat)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _draw(state: TableState, seat: PlayerId, intent: Draw) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    if intent.deck.side is Side.FATE:
        card = ops.draw_to_hand(state, seat)
        if card is None:
            return []
        dest: MoveDest = ZoneKey(seat, ZoneRole.HAND)
        position = None
    else:
        card = state.decks[intent.deck].draw_one()
        if card is None:
            return []
        dest = BATTLEFIELD
        position = None
        for key, zone in state.zones.items():
            if key.owner == seat and key.role is ZoneRole.PROVINCE and zone.has_capacity():
                card.turn_face_down()
                zone.add(card)
                dest = key
                break
        if dest == BATTLEFIELD:
            card.turn_face_down()
            state.battlefield.add(card)
            position = UNPLACED_BOARD_POS
            state.positions[card.id] = position
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest, position), (card.id,))]


def _shuffle(state: TableState, seat: PlayerId, intent: Shuffle) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    state.decks[intent.deck].shuffle(default_rng(intent.seed))
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _flip_deck_top(state: TableState, seat: PlayerId, intent: FlipDeckTop) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    cards = state.decks[intent.deck].cards
    if not cards:
        return []
    top = cards[-1]
    top.flip()
    state.seq += 1
    return [Event(state.seq, seat, intent, (top.id,))]


def _search_deck(state: TableState, seat: PlayerId, intent: SearchDeck) -> list[Event]:
    # Read-only: the accepted event signals the web layer to ship the ordered deck to its owner
    # alone; state and seq are untouched. A non-owner is rejected here and receives nothing.
    if not owns_deck(state, seat, intent.deck):
        return []
    return [Event(state.seq, seat, intent)]


def _fill_province(state: TableState, seat: PlayerId, intent: FillProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    if not zone.has_capacity():
        return []
    card = ops.fill_province(state, seat, zone)
    if card is None:
        return []
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, intent.zone), (card.id,))]


def _destroy_province(state: TableState, seat: PlayerId, intent: DestroyProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    moved = ops.destroy_province(state, seat, intent.zone)
    state.seq += 1
    return [Event(state.seq, seat, intent, tuple(moved))]


def _discard_province(state: TableState, seat: PlayerId, intent: DiscardProvince) -> list[Event]:
    zone = state.zones.get(intent.zone)
    if (
        zone is None
        or not isinstance(zone, ProvinceZone)
        or not owns_zone(state, seat, intent.zone)
    ):
        return []
    card = ops.discard_province(state, seat, zone)
    if card is None:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _create_province(state: TableState, seat: PlayerId, intent: CreateProvince) -> list[Event]:
    ops.create_province(state, seat)
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _set_honor(state: TableState, seat: PlayerId, intent: SetHonor) -> list[Event]:
    if not ops.set_honor(state, seat, delta=intent.delta, value=intent.value):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _spawn_card(state: TableState, seat: PlayerId, intent: SpawnCard) -> list[Event]:
    if intent.card_id in state.cards_by_id:
        return []
    # Resolve the one source the spawn copies. Any loaded token or publicly visible card is
    # spawnable: the per-card "Create" menu's owner-gate is cosmetic (client-side), so the only
    # server restrictions are a known token id and a source whose identity is already public.
    if intent.token_id is not None:
        source = state.creatable_tokens.get(intent.token_id)
    elif intent.source_card_id is not None:
        src = state.cards_by_id.get(intent.source_card_id)
        if src is None or not card_identity_public(state, intent.source_card_id):
            return []
        source = src.active_face
    else:
        source = intent.printed
    if source is None:
        return []
    if intent.zone is not None and not owns_zone(state, seat, intent.zone):
        return []
    card = ops.spawn_token(
        state,
        intent.card_id,
        source,
        owner=seat,
        dest=BATTLEFIELD if intent.zone is None else intent.zone,
        position=intent.position,
    )
    if card is None:
        return []
    if intent.shown:
        card.show()
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _remove_card(state: TableState, seat: PlayerId, intent: RemoveCard) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None:
        return []
    # Taking the Favor has to clear the proxy wherever it sits, including an opponent's hand, so the
    # owner gate is lifted for rulebook proxies alone. Widening this to tokens generally would mean
    # any seat could delete any token another seat made.
    if card.printed_id not in RULEBOOK_PROXY_IDS and not owns_card(state, seat, intent.card_id):
        return []
    # Only spawned tokens may leave the table outright; a real card from a deck or zone is never
    # destroyable and must instead be moved to a discard or banish.
    if not card.is_token:
        return []
    ops.remove_card(state, card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


def _on_battlefield(state: TableState, card: L5RCard) -> bool:
    return any(held is card for held in state.battlefield.cards)


def _attach(state: TableState, seat: PlayerId, intent: Attach) -> list[Event]:
    child = state.cards_by_id.get(intent.card_id)
    if (
        child is None
        or not owns_card(state, seat, intent.card_id)
        or not _on_battlefield(state, child)
    ):
        return []
    target = intent.to
    if isinstance(target, ZoneKey):
        if not isinstance(state.zones.get(target), ProvinceZone):
            return []
    else:
        parent = state.cards_by_id.get(target)
        if parent is None or not _on_battlefield(state, parent):
            return []
        # Refuse a self-attach or cycle: walking parents from the target must not reach the child.
        cursor: AttachTarget | None = target
        while isinstance(cursor, str):
            if cursor == intent.card_id:
                return []
            cursor = state.attachments.get(cursor)
    if not ops.stack(state, child, target):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (child.id,))]


def _detach(state: TableState, seat: PlayerId, intent: Detach) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    if not ops.unstack(state, card):
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _flip_coin(state: TableState, seat: PlayerId, intent: FlipCoin) -> list[Event]:
    # Read-only: the coin touches no piece, so state and seq are untouched. The result rides on the
    # intent, so both seats and any replay show the same side.
    return [Event(state.seq, seat, intent)]


def _roll_dice(state: TableState, seat: PlayerId, intent: RollDice) -> list[Event]:
    # Read-only, mirroring _flip_coin: the die changes nothing and the face rides on the intent.
    return [Event(state.seq, seat, intent)]


_HANDLERS = {
    IntentOp.MOVE_CARD: _move_card,
    IntentOp.MOVE_DECK_TOP: _move_deck_top,
    IntentOp.SET_CARD_POS: _set_card_pos,
    IntentOp.SET_CARD_POSITIONS: _set_card_positions,
    IntentOp.REORDER_HAND: _reorder_hand,
    IntentOp.REORDER_PILE: _reorder_pile,
    IntentOp.RAISE: _raise,
    IntentOp.SET_NOTE: _set_note,
    IntentOp.ADJUST_COUNTER: _adjust_counter,
    IntentOp.GIVE_CONTROL: _give_control,
    IntentOp.BOW: _apply_flag,
    IntentOp.UNBOW: _apply_flag,
    IntentOp.FLIP: _apply_flag,
    IntentOp.FLIP_FACE: _apply_flag,
    IntentOp.INVERT: _apply_flag,
    IntentOp.SHOW: _show,
    IntentOp.UNSHOW: _unshow,
    IntentOp.PEEK: _peek,
    IntentOp.UNPEEK: _unpeek,
    IntentOp.DRAW: _draw,
    IntentOp.SHUFFLE: _shuffle,
    IntentOp.FLIP_DECK_TOP: _flip_deck_top,
    IntentOp.SEARCH_DECK: _search_deck,
    IntentOp.FILL_PROVINCE: _fill_province,
    IntentOp.DESTROY_PROVINCE: _destroy_province,
    IntentOp.DISCARD_PROVINCE: _discard_province,
    IntentOp.CREATE_PROVINCE: _create_province,
    IntentOp.SET_HONOR: _set_honor,
    IntentOp.SPAWN_CARD: _spawn_card,
    IntentOp.REMOVE_CARD: _remove_card,
    IntentOp.ATTACH: _attach,
    IntentOp.DETACH: _detach,
    IntentOp.FLIP_COIN: _flip_coin,
    IntentOp.ROLL_DICE: _roll_dice,
}


# Actions a particular card refuses, whoever is acting. One entry per exception rather than a rule
# about a category of card: the Imperial Favor is public for as long as it is held, so its holder
# has no way to hide it.
LOCKED_ACTIONS: dict[str, frozenset[IntentOp]] = {
    IMPERIAL_FAVOR_ID: frozenset({IntentOp.UNSHOW}),
}


def locked_ops(card: L5RCard) -> frozenset[IntentOp]:
    """The intents ``card`` refuses regardless of who is acting, for the client to leave off its
    menu and for :func:`~.apply_intent` to reject."""
    return LOCKED_ACTIONS.get(card.printed_id, frozenset())


def _locked(state: TableState, intent: Intent) -> bool:
    """Whether any card the intent targets refuses its op. A batch is all-or-nothing, matching the
    ownership gate."""
    card_ids = getattr(intent, "card_ids", None)
    if card_ids is None:
        target = getattr(intent, "card_id", None)
        card_ids = () if target is None else (target,)
    return any(
        (card := state.cards_by_id.get(card_id)) is not None and intent.op in locked_ops(card)
        for card_id in card_ids
    )


def apply_intent(state: TableState, seat: PlayerId, intent: Intent) -> list[Event]:
    """Validate and apply one intent, mutating ``state`` in place and returning the events produced.

    Pure apart from the in-place mutation: no I/O, deterministic given the state, seat, and intent
    (shuffles derive their order from the intent's explicit seed). Ownership, side, and capacity
    violations are rejected and leave the state untouched, returning an empty list. ``seq`` advances
    only when the table actually changes.

    Parameters
    ----------
    state : TableState
        The authoritative table, mutated in place on an accepted intent.
    seat : PlayerId
        The seat attempting the action.
    intent : Intent
        The operation to apply.
    """
    if _locked(state, intent):
        return []
    return _HANDLERS[intent.op](state, seat, intent)
