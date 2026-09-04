from collections.abc import Container
from typing import Literal

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    BATTLEFIELD,
    DEFAULT_BOARD_POS,
    AttachTarget,
    BoardPos,
    DeckKey,
    Location,
    MoveDest,
    TableState,
    ZoneKey,
    ZoneRole,
    location_of,
    unit_members,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint, PersonalityPrint

# The fundamental table mutations: pure, in-place changes to a TableState with no ownership gates,
# no version bump, and no event building. The manual sim (intents.apply_intent) wraps these with
# gates and events; the rules engine drives the same ops from its own legality layer; and
# state-analysis / QoL features (force counting, token tracking) read the same board these ops
# shape. Card-state flags (bow/flip/show/note/...) are already methods on L5RCard, not duplicated.


def remove_from_location(state: TableState, card: L5RCard) -> None:
    """Remove ``card`` (by identity) from whatever zone, deck, or the battlefield holds it, dropping
    any battlefield position and location."""
    for container in (*state.zones.values(), *state.decks.values(), state.battlefield):
        cards = container.cards
        for i, held in enumerate(cards):
            if held is card:
                del cards[i]
                state.positions.pop(card.id, None)
                state.locations.pop(card.id, None)
                return


def _clear_relations(state: TableState, card_id: str) -> None:
    """Drop ``card_id`` from every relation in both roles: its own link to a parent, and anything
    hung off it. Called when the card leaves the battlefield, so nothing ever references a card that
    is no longer in play."""
    state.attachments.pop(card_id, None)
    for child in [c for c, parent in state.attachments.items() if parent == card_id]:
        del state.attachments[child]
    state.units.pop(card_id, None)
    for member in [c for c, personality in state.units.items() if personality == card_id]:
        del state.units[member]
    state.province_attachments.pop(card_id, None)


def bring_to_top(state: TableState, card: L5RCard) -> None:
    """Move ``card`` to the end of the battlefield list (the top of the rendered stack)."""
    cards = state.battlefield.cards
    for i, held in enumerate(cards):
        if held is card:
            if i != len(cards) - 1:
                cards.append(cards.pop(i))
            return


def _holds_tokens(dest: MoveDest) -> bool:
    """Whether a created card that is not in play may sit at ``dest``. Only a hand may, and only
    because a rulebook proxy is represented by one there; every pile of real cards destroys it."""
    return isinstance(dest, ZoneKey) and dest.role is ZoneRole.HAND


def move_card(
    state: TableState,
    card: L5RCard,
    dest: MoveDest,
    *,
    position: BoardPos | None = None,
    to_bottom: bool = False,
    index: int | None = None,
    deck_index: int | None = None,
) -> bool:
    """Move ``card`` to a zone, deck, or the shared battlefield, applying the destination's entry
    effects (a card faces up entering a hand or discard, unbows entering a province, and is scrubbed
    to a pristine library card entering a deck — face down, unbowed, uninverted, its note and every
    show/peek disclosure cleared). Returns whether the table changed — a move onto the zone the card
    already occupies is a no-op.

    A card leaving the battlefield loses its counters: tokens cannot exist on a card out of play,
    and they do not come back if it re-enters (CR, Tokens). A *created* card ceases to exist rather
    than arriving (CR, Create), so ``dest`` is ignored and it is taken off the table: leaving the
    battlefield destroys it wherever it was headed, and one held in a hand as a rulebook proxy
    survives only a move to another hand.

    ``deck_index`` lands the card at that depth in a deck's bottom-first list, clamped into range,
    and takes precedence over ``to_bottom``."""
    # Enforced here rather than at each call site: every move funnels through this one.
    on_battlefield = any(held is card for held in state.battlefield.cards)
    if card.is_token and dest != BATTLEFIELD and (on_battlefield or not _holds_tokens(dest)):
        remove_card(state, card)
        return True
    # Counters exist only in play, so a real card loses them on the way out (CR, Tokens).
    if dest != BATTLEFIELD and on_battlefield:
        card.clear_counters()

    if dest == BATTLEFIELD:
        pos = position or state.positions.get(card.id) or DEFAULT_BOARD_POS
        # Read before the removal drops it: repositioning on the table is presentation, and must
        # not send an assigned unit home from its battlefield.
        location = state.locations.get(card.id)
        remove_from_location(state, card)
        state.battlefield.add(card)
        state.positions[card.id] = pos
        if location is not None:
            state.locations[card.id] = location
        return True

    if isinstance(dest, DeckKey):
        remove_from_location(state, card)
        _clear_relations(state, card.id)
        # Anonymize the card for the shuffle back into the library — no seat may read a deck card.
        card.turn_face_down()
        card.unbow()
        card.uninvert()
        card.set_note(None)
        card.unshow()
        card.clear_peekers()
        deck = state.decks[dest]
        if deck_index is not None:
            deck.cards.insert(max(0, min(deck_index, len(deck.cards))), card)
        elif to_bottom:
            deck.add_to_bottom([card])
        else:
            deck.add_to_top([card])
        return True

    zone = state.zones[dest]
    if any(held is card for held in zone.cards):
        return False
    remove_from_location(state, card)
    _clear_relations(state, card.id)
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


def set_location(state: TableState, card: L5RCard, location: Location) -> bool:
    """Record where ``card`` stands, returning whether it moved.

    A card at its own owner's home is stored as no entry at all, so each board position has one
    representation. Read it back through :func:`~yasuki_core.engine.table.location_of`. Raise
    ``ValueError`` on a location naming neither a home nor a battlefield.
    """
    if not location.is_well_formed():
        raise ValueError(f"location names neither a home nor a battlefield: {location}")
    default = Location.home(card.owner)
    recorded = state.locations.get(card.id)
    if location == default:
        state.locations.pop(card.id, None)
    else:
        state.locations[card.id] = location
    return location != (default if recorded is None else recorded)


def move_unit(state: TableState, card: L5RCard, location: Location) -> bool:
    """Put ``card``'s whole unit at ``location``; returns whether it moved.

    Attached cards go with their Personality (CR, Unit). Nothing here goes through
    :func:`move_card` — the cards stay where they are in play and only their location changes.
    """
    moved = False
    for member in unit_members(state, card):
        if set_location(state, member, location):
            moved = True
    return moved


def assign(state: TableState, card: L5RCard, battlefield: int) -> bool:
    """Assign ``card``'s whole unit to the battlefield at index ``battlefield``; returns whether it
    moved. Assigning is *not* movement (CR, Assign), whatever it shares with it here.
    """
    return move_unit(state, card, Location.at_battlefield(battlefield))


def return_home(state: TableState, card: L5RCard) -> bool:
    """Send ``card``'s whole unit home; returns whether it moved. Home is the unit's — its
    Personality's owner's — so an attached card owned by the other seat goes where its Personality
    goes.
    """
    return move_unit(state, card, Location.home(card.owner))


def stack(state: TableState, card: L5RCard, target: AttachTarget) -> bool:
    """Stack ``card`` behind ``target`` — a card id or province zone key — so it renders behind that
    parent. Returns whether the graph changed; re-stacking on the same target is a no-op.

    Rendering only; :func:`attach_to_personality` is what puts a card in a unit.
    """
    if state.attachments.get(card.id) == target:
        return False
    state.attachments[card.id] = target
    return True


def unstack(state: TableState, card: L5RCard) -> bool:
    """Unstack ``card`` from the card or province it renders behind, leaving anything stacked on it
    in place. Returns whether it was stacked."""
    return state.attachments.pop(card.id, None) is not None


def attach_to_personality(state: TableState, card: L5RCard, personality: L5RCard) -> bool:
    """Attach ``card`` to ``personality``, putting it in his unit. Returns whether the relation
    changed; re-attaching to the same Personality is a no-op.

    Raises
    ------
    ValueError
        If ``personality`` is not a Personality. Attachments are the only card type that may attach
        to a Personality and a Personality is the only thing they may attach to (CR, Attachments), so
        a wrong parent is a caller bug rather than a board state to represent.
    """
    if not isinstance(personality.printed, PersonalityPrint):
        raise ValueError(f"cannot attach {card.id!r} to non-Personality {personality.id!r}")
    # A card in a unit stands where its Personality stands (CR, Unit), so one equipped to a
    # Personality already at a battlefield is at that battlefield rather than at home.
    set_location(state, card, location_of(state, personality))
    if state.units.get(card.id) == personality.id:
        return False
    state.units[card.id] = personality.id
    state.province_attachments.pop(card.id, None)
    return True


def attach_to_province(state: TableState, card: L5RCard, zone_key: ZoneKey) -> bool:
    """Attach ``card`` to a province, where Regions and Fortifications sit. Returns whether the
    relation changed."""
    if state.province_attachments.get(card.id) == zone_key:
        return False
    state.province_attachments[card.id] = zone_key
    state.units.pop(card.id, None)
    return True


def detach(state: TableState, card: L5RCard) -> bool:
    """Break ``card``'s attachment to whichever Personality or province holds it, leaving its
    stacking alone. Returns whether it was attached to either."""
    in_unit = state.units.pop(card.id, None) is not None
    on_province = state.province_attachments.pop(card.id, None) is not None
    return in_unit or on_province


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


def fill_province(
    state: TableState, seat: PlayerId, zone: ProvinceZone, *, face_up: bool = False
) -> L5RCard | None:
    """Draw the seat's top dynasty card into ``zone``; None if the dynasty deck is empty.

    Parameters
    ----------
    face_up : bool, optional
        Whether the card arrives face-up, as a Renew refill does. It arrives in that state rather
        than being turned into it, so a face-up arrival is never a reveal. Default False.
    """
    card = state.decks[DeckKey(seat, Side.DYNASTY)].draw_one()
    if card is None:
        return None
    card.unbow()
    if face_up:
        card.turn_face_up()
    else:
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
    state.province_counters.pop(zone_key, None)  # the slot is gone; nothing rests on it
    # A card attached to the province follows it off the board into its own side's discard; move_card
    # turns it face up and clears the attachment. Only fate/dynasty cards have a discard — a pregame
    # side (stronghold/sensei/wind) has none, so it just detaches rather than vanishing off the board.
    stacked = [child for child, parent in state.attachments.items() if parent == zone_key]
    attached = [child for child, parent in state.province_attachments.items() if parent == zone_key]
    # A card can be both stacked behind the province and attached to it; it follows the province off
    # the board once.
    children = dict.fromkeys(stacked + attached)
    for child_id in children:
        child = state.cards_by_id[child_id]
        if child.side is Side.FATE:
            role = ZoneRole.FATE_DISCARD
        elif child.side is Side.DYNASTY:
            role = ZoneRole.DYNASTY_DISCARD
        else:
            state.attachments.pop(child_id, None)
            state.province_attachments.pop(child_id, None)
            continue
        move_card(state, child, ZoneKey(child.owner or seat, role))
        moved.append(child_id)
    return moved


def adjust_province_counter(state: TableState, zone_key: ZoneKey, name: str, delta: int) -> int:
    """Add ``delta`` counters of ``name`` to a Province, floored at zero, and return the new count.
    A Province holding none of a counter carries no entry for it."""
    held = state.province_counters.setdefault(zone_key, {})
    count = max(0, held.get(name, 0) + delta)
    if count:
        held[name] = count
    else:
        held.pop(name, None)
        if not held:
            state.province_counters.pop(zone_key, None)
    return count


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


def straighten(state: TableState, seat: PlayerId, skip: Container[str] = ()) -> list[str]:
    """Unbow every card ``seat`` controls on the battlefield, other than the ids in ``skip``;
    returns the straightened card ids. What may be left bowed is the rules layer's to decide, so the
    caller names the cards rather than this reading a card's text."""
    straightened = []
    for card in state.battlefield.cards:
        if card.owner == seat and card.bowed and card.id not in skip:
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


def spawn_token(
    state: TableState,
    new_id: str,
    printed: CardPrint,
    owner: PlayerId,
    *,
    dest: ZoneKey | Literal["battlefield"] = BATTLEFIELD,
    position: BoardPos | None = None,
) -> L5RCard | None:
    """Place a fresh face-up token presenting ``printed`` at ``dest``, defaulting to the battlefield
    at ``position``. Returns None when a zone refuses the card for its side or capacity; a
    battlefield spawn always succeeds.

    The token carries the print's type, stats, keywords, and text under a new id, with no per-copy
    state. It is face up, so both seats see it; ``owner`` gates who may move or remove it, not who
    may see it.

    A created card cannot be moved into a zone afterwards — leaving the battlefield destroys it
    (CR, Create) — so a token that belongs in a hand has to be spawned there directly.
    """
    card = L5RCard(id=new_id, printed=printed, owner=owner, is_token=True)
    if dest == BATTLEFIELD:
        state.battlefield.add(card)
        state.positions[card.id] = DEFAULT_BOARD_POS if position is None else position
    elif not state.zones[dest].add(card):
        return None
    state.cards_by_id[card.id] = card
    return card


def remove_card(state: TableState, card: L5RCard) -> None:
    """Take ``card`` off the table entirely, wherever it sits."""
    del state.cards_by_id[card.id]
    remove_from_location(state, card)
    _clear_relations(state, card.id)


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


def set_ignore_honor_requirements(state: TableState, seat: PlayerId, value: bool) -> bool:
    """Set whether ``seat`` waives every Personality's Honor Requirement when recruiting; returns
    whether it changed."""
    info = state.seats[seat]
    if info.ignores_honor_requirements == value:
        return False
    info.ignores_honor_requirements = value
    return True
