from dataclasses import replace

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    BATTLEFIELD,
    DEFAULT_BOARD_POS,
    AttachTarget,
    BoardPos,
    DeckKey,
    MoveDest,
    TableState,
    ZoneKey,
    ZoneRole,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side

# The fundamental table mutations: pure, in-place changes to a TableState with no ownership gates,
# no version bump, and no event building. The manual sim (intents.apply_intent) wraps these with
# gates and events; the rules engine drives the same ops from its own legality layer; and
# state-analysis / QoL features (force counting, token tracking) read the same board these ops
# shape. Card-state flags (bow/flip/show/note/...) are already methods on L5RCard, not duplicated.


def remove_from_location(state: TableState, card: L5RCard) -> None:
    """Remove ``card`` (by identity) from whatever zone, deck, or the battlefield holds it, dropping
    any battlefield position."""
    for container in (*state.zones.values(), *state.decks.values(), state.battlefield):
        cards = container.cards
        for i, held in enumerate(cards):
            if held is card:
                del cards[i]
                state.positions.pop(card.id, None)
                return


def _clear_attachment(state: TableState, card_id: str) -> None:
    """Drop ``card_id`` from the attachment graph in both roles: its own link to a parent, and any
    children hung off it. Called when the card leaves the battlefield, so no attachment ever dangles
    on a card that is no longer in play."""
    state.attachments.pop(card_id, None)
    for child in [c for c, parent in state.attachments.items() if parent == card_id]:
        del state.attachments[child]


def bring_to_top(state: TableState, card: L5RCard) -> None:
    """Move ``card`` to the end of the battlefield list (the top of the rendered stack)."""
    cards = state.battlefield.cards
    for i, held in enumerate(cards):
        if held is card:
            if i != len(cards) - 1:
                cards.append(cards.pop(i))
            return


def move_card(
    state: TableState,
    card: L5RCard,
    dest: MoveDest,
    *,
    position: BoardPos | None = None,
    to_bottom: bool = False,
    index: int | None = None,
) -> bool:
    """Move ``card`` to a zone, deck, or the shared battlefield, applying the destination's entry
    effects (a card faces up entering a hand or discard, unbows entering a province, and is scrubbed
    to a pristine library card entering a deck — face down, unbowed, uninverted, its note and every
    show/peek disclosure cleared). Returns whether the table changed — a move onto the zone the card
    already occupies is a no-op."""
    if dest == BATTLEFIELD:
        pos = position or state.positions.get(card.id) or DEFAULT_BOARD_POS
        remove_from_location(state, card)
        state.battlefield.add(card)
        state.positions[card.id] = pos
        return True

    if isinstance(dest, DeckKey):
        remove_from_location(state, card)
        _clear_attachment(state, card.id)
        # Anonymize the card for the shuffle back into the library — no seat may read a deck card.
        card.turn_face_down()
        card.unbow()
        card.uninvert()
        card.set_note(None)
        card.unshow()
        card.clear_peekers()
        deck = state.decks[dest]
        if to_bottom:
            deck.add_to_bottom([card])
        else:
            deck.add_to_top([card])
        return True

    zone = state.zones[dest]
    if any(held is card for held in zone.cards):
        return False
    remove_from_location(state, card)
    _clear_attachment(state, card.id)
    if dest.role is ZoneRole.HAND:
        card.turn_face_up()
        card.unbow()
        card.uninvert()
    elif dest.role is ZoneRole.PROVINCE:
        card.unbow()
    elif dest.role in (ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD):
        card.turn_face_up()
        card.unbow()
    if dest.role is ZoneRole.HAND and index is not None:
        zone.cards.insert(max(0, min(index, len(zone.cards))), card)
    else:
        zone.add(card)
    return True


def set_position(state: TableState, card: L5RCard, x: float, y: float) -> bool:
    """Reposition a battlefield card and raise it to the top. Returns whether the position
    changed."""
    new_pos = BoardPos(x, y)
    if state.positions.get(card.id) == new_pos:
        return False
    state.positions[card.id] = new_pos
    bring_to_top(state, card)
    return True


def attach(state: TableState, card: L5RCard, target: AttachTarget) -> bool:
    """Attach ``card`` to ``target`` — a parent card id or province zone key — so it rides behind
    that parent. Returns whether the graph changed; re-attaching to the same target is a no-op."""
    if state.attachments.get(card.id) == target:
        return False
    state.attachments[card.id] = target
    return True


def detach(state: TableState, card: L5RCard) -> bool:
    """Break ``card``'s own attachment to its parent, leaving anything hung off ``card`` in place.
    Returns whether it was attached."""
    return state.attachments.pop(card.id, None) is not None


def reorder_in_hand(state: TableState, seat: PlayerId, card_id: str, index: int) -> bool:
    """Move a card within ``seat``'s hand to ``index`` (clamped). Returns whether the order
    changed."""
    hand = state.zones.get(ZoneKey(seat, ZoneRole.HAND))
    if hand is None:
        return False
    cards = hand.cards
    current = next((i for i, held in enumerate(cards) if held.id == card_id), None)
    if current is None:
        return False
    card = cards.pop(current)
    target = max(0, min(index, len(cards)))
    cards.insert(target, card)
    return target != current


def reorder_in_pile(state: TableState, pile: DeckKey | ZoneKey, card_id: str, index: int) -> bool:
    """Move a card within a deck or pile to ``index`` in the owner's top-first view (the engine list
    keeps the top last). Returns whether the order changed."""
    if isinstance(pile, DeckKey):
        holder = state.decks.get(pile)
    elif isinstance(pile, ZoneKey):
        holder = state.zones.get(pile)
    else:
        return False
    cards = holder.cards if holder is not None else None
    if not cards:
        return False
    view = list(reversed(cards))
    current = next((i for i, held in enumerate(view) if held.id == card_id), None)
    if current is None:
        return False
    card = view.pop(current)
    target = max(0, min(index, len(view)))
    view.insert(target, card)
    if target == current:
        return False
    cards[:] = reversed(view)
    return True


def fill_province(state: TableState, seat: PlayerId, zone: ProvinceZone) -> L5RCard | None:
    """Draw the seat's top dynasty card face-down into ``zone``; None if the dynasty deck is
    empty."""
    card = state.decks[DeckKey(seat, Side.DYNASTY)].draw_one()
    if card is None:
        return None
    card.unbow()
    card.turn_face_down()
    zone.add(card)
    return card


def draw_to_hand(state: TableState, seat: PlayerId) -> L5RCard | None:
    """Draw the seat's top fate card into their hand face-up; None if the fate deck is empty."""
    card = state.decks[DeckKey(seat, Side.FATE)].draw_one()
    if card is None:
        return None
    card.turn_face_up()
    state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
    return card


def destroy_province(state: TableState, seat: PlayerId, zone_key: ZoneKey) -> list[str]:
    """Discard a province's contents face-up and remove the province, then send each card attached to
    it (fortifications, regions) to its own side's discard — the owner's pile if it has one, else the
    destroying seat's. A card with no discard for its side (a pregame permanent) is detached in place.
    Returns the moved card ids."""
    zone = state.zones[zone_key]
    discard = state.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)]
    moved = []
    while zone.cards:
        card = zone.cards.pop()
        card.turn_face_up()
        discard.add(card)
        moved.append(card.id)
    del state.zones[zone_key]
    # A card attached to the province follows it off the board into its own side's discard; move_card
    # turns it face up and clears the attachment. Only fate/dynasty cards have a discard — a pregame
    # side (stronghold/sensei/wind) has none, so it just detaches rather than vanishing off the board.
    for child_id in [child for child, parent in state.attachments.items() if parent == zone_key]:
        child = state.cards_by_id[child_id]
        if child.side is Side.FATE:
            role = ZoneRole.FATE_DISCARD
        elif child.side is Side.DYNASTY:
            role = ZoneRole.DYNASTY_DISCARD
        else:
            state.attachments.pop(child_id, None)
            continue
        move_card(state, child, ZoneKey(child.owner or seat, role))
        moved.append(child_id)
    return moved


def discard_province(state: TableState, seat: PlayerId, zone: ProvinceZone) -> L5RCard | None:
    """Move the province's top card to the dynasty discard face-up; None if empty."""
    if not zone.cards:
        return None
    card = zone.cards.pop()
    card.turn_face_up()
    state.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].add(card)
    return card


def create_province(state: TableState, seat: PlayerId) -> ZoneKey:
    """Add a fresh province zone for ``seat`` at the next free index; returns its key."""
    idx = 0
    while ZoneKey(seat, ZoneRole.PROVINCE, idx) in state.zones:
        idx += 1
    key = ZoneKey(seat, ZoneRole.PROVINCE, idx)
    state.zones[key] = ProvinceZone(owner=seat)
    return key


def straighten(state: TableState, seat: PlayerId) -> list[str]:
    """Unbow every card ``seat`` controls on the battlefield; returns the straightened card ids."""
    straightened = []
    for card in state.battlefield.cards:
        if card.owner == seat and card.bowed:
            card.unbow()
            straightened.append(card.id)
    return straightened


def reveal_provinces(state: TableState, seat: PlayerId) -> list[str]:
    """Turn every face-down card in ``seat``'s provinces face-up; returns the revealed card ids."""
    revealed = []
    for key, zone in state.zones.items():
        if key.owner == seat and key.role is ZoneRole.PROVINCE:
            for card in zone.cards:
                if not card.face_up:
                    card.turn_face_up()
                    revealed.append(card.id)
    return revealed


def spawn_token(state: TableState, new_id: str, template: L5RCard, position: BoardPos) -> L5RCard:
    """Place a fresh public, face-up token onto the battlefield at ``position``.

    The token is a copy of ``template`` (a full card, so it carries the template's type, stats,
    keywords, and text) under a new id, stripped of any per-instance state and marked a token.
    """
    card = replace(
        template,
        id=new_id,
        owner=None,
        is_token=True,
        face_up=True,
        bowed=False,
        inverted=False,
        shown=False,
        peekers=frozenset(),
        showing_back=False,
        note=None,
    )
    state.cards_by_id[card.id] = card
    state.battlefield.add(card)
    state.positions[card.id] = position
    return card


def remove_card(state: TableState, card: L5RCard) -> None:
    """Take ``card`` off the table entirely, wherever it sits."""
    del state.cards_by_id[card.id]
    remove_from_location(state, card)
    _clear_attachment(state, card.id)


def set_honor(
    state: TableState, seat: PlayerId, *, delta: int | None = None, value: int | None = None
) -> bool:
    """Adjust ``seat``'s honor by ``delta`` or to ``value``; returns whether it changed."""
    info = state.seats[seat]
    new_honor = info.honor + delta if delta is not None else value
    if new_honor == info.honor:
        return False
    info.honor = new_honor
    return True
