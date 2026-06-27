from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import NamedTuple, ClassVar, Literal, Final
from collections.abc import Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import (
    Zone,
    HandZone,
    BattlefieldZone,
    ProvinceZone,
    FateDiscardZone,
    FateBanishZone,
    DynastyDiscardZone,
    DynastyBanishZone,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.deck import Deck, FateDeck, DynastyDeck


class ZoneRole(str, Enum):
    HAND = "hand"
    FATE_DISCARD = "fate_discard"
    FATE_BANISH = "fate_banish"
    DYNASTY_DISCARD = "dynasty_discard"
    DYNASTY_BANISH = "dynasty_banish"
    PROVINCE = "province"


# Per-seat zones present from table construction; provinces are created on demand
# (CREATE_PROVINCE) and so are absent here.
_FIXED_ZONES: tuple[tuple[ZoneRole, type[Zone]], ...] = (
    (ZoneRole.HAND, HandZone),
    (ZoneRole.FATE_DISCARD, FateDiscardZone),
    (ZoneRole.FATE_BANISH, FateBanishZone),
    (ZoneRole.DYNASTY_DISCARD, DynastyDiscardZone),
    (ZoneRole.DYNASTY_BANISH, DynastyBanishZone),
)


class ZoneKey(NamedTuple):
    owner: PlayerId
    role: ZoneRole
    idx: int | None = None  # set only for PROVINCE; None otherwise


class DeckKey(NamedTuple):
    owner: PlayerId
    side: Side  # FATE or DYNASTY


class BoardPos(NamedTuple):
    x: float
    y: float


@dataclass(slots=True)
class SeatInfo:
    name: str
    honor: int = 0  # set from the stronghold + sensei at setup; 0 until then
    ready: bool = False
    connected: bool = False


@dataclass(slots=True)
class TableState:
    """Authoritative, per-room game state.

    Holds the full truth for one table: both seats, every zone and deck, the shared
    battlefield, and an identity map from card id to card. Mutations bump ``seq`` so clients can
    detect dropped messages and request a fresh snapshot.

    Attributes
    ----------
    seats : dict mapping PlayerId to SeatInfo
        The two seats and their public status (name, honor, ready, connected).
    zones : dict mapping ZoneKey to Zone
        Owned, role-keyed zones (hands, discards, banishes, provinces).
    decks : dict mapping DeckKey to Deck
        Each seat's fate and dynasty decks.
    battlefield : BattlefieldZone
        Shared, public play area; member cards have a position in ``positions``.
    positions : dict mapping str to BoardPos
        Table coordinates for battlefield cards, keyed by card id.
    cards_by_id : dict mapping str to L5RCard
        Identity map over every card on the table, for fast intent lookup.
    seq : int
        Monotonic version stamp; every accepted mutation increments it.
    """

    seats: dict[PlayerId, SeatInfo]
    zones: dict[ZoneKey, Zone]
    decks: dict[DeckKey, Deck]
    battlefield: BattlefieldZone
    # L5RCard is frozen, so battlefield positions live here, keyed by card id, not on the card.
    positions: dict[str, BoardPos] = field(default_factory=dict)
    cards_by_id: dict[str, L5RCard] = field(default_factory=dict)
    seq: int = 0

    @classmethod
    def empty_two_seat(cls, p1_name: str = "P1", p2_name: str = "P2") -> "TableState":
        """Build an empty, ready-to-fill two-seat table.

        Each seat gets its fixed zones (hand, discards, banishes) and empty fate/dynasty decks.
        Provinces, deck contents, and starting honor are populated later at deck-load setup.

        Parameters
        ----------
        p1_name : str, optional
            Display name for seat P1. Default 'P1'.
        p2_name : str, optional
            Display name for seat P2. Default 'P2'.
        """
        seats = {
            PlayerId.P1: SeatInfo(name=p1_name),
            PlayerId.P2: SeatInfo(name=p2_name),
        }
        zones: dict[ZoneKey, Zone] = {}
        decks: dict[DeckKey, Deck] = {}
        for seat in PlayerId:
            for role, zone_cls in _FIXED_ZONES:
                zones[ZoneKey(seat, role)] = zone_cls(owner=seat)
            decks[DeckKey(seat, Side.FATE)] = FateDeck(cards=[])
            decks[DeckKey(seat, Side.DYNASTY)] = DynastyDeck(cards=[])
        return cls(seats=seats, zones=zones, decks=decks, battlefield=BattlefieldZone())

    def iter_all_cards(self) -> Iterator[L5RCard]:
        """Yield every card located on the table, across all zones, decks, and the battlefield."""
        for zone in self.zones.values():
            yield from zone.cards
        for deck in self.decks.values():
            yield from deck.cards
        yield from self.battlefield.cards

    def validate(self) -> None:
        """Check the table's structural invariants, raising ``ValueError`` on the first violation.

        Verifies that card ids are unique across the whole table, that ``cards_by_id`` indexes
        exactly the located cards, that battlefield positions reference only battlefield cards, and
        that every zone and deck key is well-formed (known owner, province-only ``idx``, matching
        zone owner, fate/dynasty deck side).
        """
        located: dict[str, L5RCard] = {}
        for card in self.iter_all_cards():
            if card.id in located:
                raise ValueError(f"Duplicate card id on table: {card.id!r}")
            located[card.id] = card
        if set(self.cards_by_id) != set(located):
            raise ValueError("cards_by_id is out of sync with located cards")

        battlefield_ids = {card.id for card in self.battlefield.cards}
        stray = set(self.positions) - battlefield_ids
        if stray:
            raise ValueError(f"positions reference non-battlefield cards: {sorted(stray)}")

        for key, zone in self.zones.items():
            if key.owner not in self.seats:
                raise ValueError(f"zone key has unknown owner: {key}")
            if key.role is ZoneRole.PROVINCE:
                if not isinstance(key.idx, int) or key.idx < 0:
                    raise ValueError(f"province zone needs a non-negative idx: {key}")
            elif key.idx is not None:
                raise ValueError(f"non-province zone must not carry an idx: {key}")
            if zone.owner != key.owner:
                raise ValueError(f"zone owner {zone.owner} does not match key {key}")

        for key, deck in self.decks.items():
            if key.owner not in self.seats:
                raise ValueError(f"deck key has unknown owner: {key}")
            if key.side not in (Side.FATE, Side.DYNASTY):
                raise ValueError(f"deck side must be FATE or DYNASTY: {key}")


class IntentOp(str, Enum):
    MOVE_CARD = "MOVE_CARD"
    MOVE_DECK_TOP = "MOVE_DECK_TOP"
    SET_CARD_POS = "SET_CARD_POS"
    SET_CARD_POSITIONS = "SET_CARD_POSITIONS"
    REORDER_HAND = "REORDER_HAND"
    RAISE = "RAISE"
    BOW = "BOW"
    UNBOW = "UNBOW"
    FLIP = "FLIP"
    FLIP_FACE = "FLIP_FACE"
    INVERT = "INVERT"
    SHOW = "SHOW"
    UNSHOW = "UNSHOW"
    PEEK = "PEEK"
    UNPEEK = "UNPEEK"
    DRAW = "DRAW"
    SHUFFLE = "SHUFFLE"
    FLIP_DECK_TOP = "FLIP_DECK_TOP"
    SEARCH_DECK = "SEARCH_DECK"
    FILL_PROVINCE = "FILL_PROVINCE"
    DESTROY_PROVINCE = "DESTROY_PROVINCE"
    DISCARD_PROVINCE = "DISCARD_PROVINCE"
    CREATE_PROVINCE = "CREATE_PROVINCE"
    SET_HONOR = "SET_HONOR"
    SPAWN_CARD = "SPAWN_CARD"
    REMOVE_CARD = "REMOVE_CARD"


# Sentinel destination for the shared battlefield in MOVE_CARD, distinct from any owned ZoneKey or
# DeckKey. A card moved here also carries a BoardPos.
BATTLEFIELD: Final = "battlefield"

# Where a card lands on the battlefield when no position is supplied.
_DEFAULT_BOARD_POS: Final = BoardPos(0.0, 0.0)

# A dynasty card drawn while every province is full lands here: a negative sentinel the client
# recognises and lays out next to the owner's dynasty deck, like an unplaced pre-game permanent.
_UNPLACED_BOARD_POS: Final = BoardPos(-1.0, -1.0)

MoveDest = ZoneKey | DeckKey | Literal["battlefield"]


@dataclass(frozen=True, slots=True)
class MoveCard:
    """Move one card to a zone, deck, or the shared battlefield.

    The universal mover behind hand↔battlefield↔zone↔deck transfers. ``position`` is set only when
    ``to`` is the battlefield, giving the card its table coordinates. ``to_bottom`` applies only to
    a deck destination: True slides the card under the deck instead of onto its top. ``index`` applies
    only to a hand destination: the slot the card lands in, clamped into range; None appends it.
    """

    card_id: str
    to: MoveDest
    position: BoardPos | None = None
    to_bottom: bool = False
    index: int | None = None
    op: ClassVar[IntentOp] = IntentOp.MOVE_CARD


@dataclass(frozen=True, slots=True)
class MoveDeckTop:
    """Pop a deck's top card and move it to a zone, deck, or the shared battlefield.

    The deck-sourced counterpart to ``MoveCard`` — for dragging a deck's top card onto the table.
    ``position`` is honored only for a battlefield destination. Owner-gated on the deck.
    """

    deck: DeckKey
    to: MoveDest
    position: BoardPos | None = None
    op: ClassVar[IntentOp] = IntentOp.MOVE_DECK_TOP


@dataclass(frozen=True, slots=True)
class SetCardPos:
    """Reposition one card freely on the shared battlefield."""

    card_id: str
    x: float
    y: float
    op: ClassVar[IntentOp] = IntentOp.SET_CARD_POS


@dataclass(frozen=True, slots=True)
class SetCardPositions:
    """Reposition several battlefield cards in one message, the wire form of a group drag. Each
    member is gated independently, so cards the seat does not own or that have left the battlefield
    are skipped rather than failing the whole move."""

    moves: tuple[tuple[str, float, float], ...]
    op: ClassVar[IntentOp] = IntentOp.SET_CARD_POSITIONS


@dataclass(frozen=True, slots=True)
class ReorderHand:
    """Move a card already in the acting seat's own hand to a new slot. The index is clamped into
    range, and a move that leaves the order unchanged produces no event."""

    card_id: str
    index: int
    op: ClassVar[IntentOp] = IntentOp.REORDER_HAND


@dataclass(frozen=True, slots=True)
class Raise:
    """Bring one battlefield card to the top of the stacking order without moving it. Owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.RAISE


@dataclass(frozen=True, slots=True)
class CardFlagIntent:
    """Base for flag operations that target one or more cards, applied atomically as a batch."""

    card_ids: tuple[str, ...]
    op: ClassVar[IntentOp]

    def __post_init__(self):
        if not isinstance(self.card_ids, tuple):
            object.__setattr__(self, "card_ids", tuple(self.card_ids))


@dataclass(frozen=True, slots=True)
class Bow(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.BOW


@dataclass(frozen=True, slots=True)
class Unbow(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.UNBOW


@dataclass(frozen=True, slots=True)
class Flip(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.FLIP


@dataclass(frozen=True, slots=True)
class FlipFace(CardFlagIntent):
    """Turn a double-faced card to its other face; a no-op for single-faced cards."""

    op: ClassVar[IntentOp] = IntentOp.FLIP_FACE


@dataclass(frozen=True, slots=True)
class Invert(CardFlagIntent):
    op: ClassVar[IntentOp] = IntentOp.INVERT


@dataclass(frozen=True, slots=True)
class Show:
    """Show one of your own cards to your opponent. Owner-gated. A face-down card stays a back to its
    owner while the opponent gains sight of it; a hand card the owner already reads becomes public to
    both seats."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.SHOW


@dataclass(frozen=True, slots=True)
class Unshow:
    """Stop showing one of your own cards to your opponent. Owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.UNSHOW


@dataclass(frozen=True, slots=True)
class Peek:
    """Privately peek at one card — your own face-down card or an opponent's. Not owner-gated: any
    seat may peek any card, and the public "peeks at a … card" log is the safeguard."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.PEEK


@dataclass(frozen=True, slots=True)
class Unpeek:
    """Stop peeking at one card, removing the acting seat from its peekers. Not owner-gated."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.UNPEEK


@dataclass(frozen=True, slots=True)
class Draw:
    """Draw the top card of a deck; routing (hand/province/battlefield) is decided on apply."""

    deck: DeckKey
    op: ClassVar[IntentOp] = IntentOp.DRAW


@dataclass(frozen=True, slots=True)
class Shuffle:
    """Shuffle a deck with an explicit seed so the new order is reproducible."""

    deck: DeckKey
    seed: int
    op: ClassVar[IntentOp] = IntentOp.SHUFFLE


@dataclass(frozen=True, slots=True)
class FlipDeckTop:
    """Flip a deck's top card face up or down in place, revealing it without drawing."""

    deck: DeckKey
    op: ClassVar[IntentOp] = IntentOp.FLIP_DECK_TOP


@dataclass(frozen=True, slots=True)
class SearchDeck:
    """Request a deck's ordered contents; the owner alone receives them. ``limit`` bounds the look to
    the top N cards (None searches the whole deck). Pulling a card is a follow-up ``MoveCard``."""

    deck: DeckKey
    limit: int | None = None
    op: ClassVar[IntentOp] = IntentOp.SEARCH_DECK


@dataclass(frozen=True, slots=True)
class FillProvince:
    """Draw a dynasty card face-down into an empty province."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.FILL_PROVINCE


@dataclass(frozen=True, slots=True)
class DestroyProvince:
    """Discard the province's contents face-up and remove the province zone."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.DESTROY_PROVINCE


@dataclass(frozen=True, slots=True)
class DiscardProvince:
    """Move the province's top card to the dynasty discard, face-up."""

    zone: ZoneKey
    op: ClassVar[IntentOp] = IntentOp.DISCARD_PROVINCE


@dataclass(frozen=True, slots=True)
class CreateProvince:
    """Add a fresh province zone for the acting seat."""

    op: ClassVar[IntentOp] = IntentOp.CREATE_PROVINCE


@dataclass(frozen=True, slots=True)
class SetHonor:
    """Adjust the acting seat's honor, either by a relative ``delta`` or to an absolute ``value``.

    Exactly one of ``delta`` or ``value`` must be given.
    """

    delta: int | None = None
    value: int | None = None
    op: ClassVar[IntentOp] = IntentOp.SET_HONOR

    def __post_init__(self):
        if (self.delta is None) == (self.value is None):
            raise ValueError("SetHonor requires exactly one of delta or value")


@dataclass(frozen=True, slots=True)
class SpawnCard:
    """Put a new public, face-up card on the shared battlefield (tokens, copies, sandbox pieces).

    The card id is assigned by the caller and recorded, so a replay reproduces the same card. The
    card is unowned (public), so either seat may then move or remove it.
    """

    card_id: str
    name: str
    side: Side
    image: str | None
    position: BoardPos
    op: ClassVar[IntentOp] = IntentOp.SPAWN_CARD


@dataclass(frozen=True, slots=True)
class RemoveCard:
    """Take a card off the table entirely, wherever it sits."""

    card_id: str
    op: ClassVar[IntentOp] = IntentOp.REMOVE_CARD


Intent = (
    MoveCard
    | MoveDeckTop
    | SetCardPos
    | SetCardPositions
    | ReorderHand
    | Raise
    | Bow
    | Unbow
    | Flip
    | FlipFace
    | Invert
    | Show
    | Unshow
    | Peek
    | Unpeek
    | Draw
    | Shuffle
    | FlipDeckTop
    | SearchDeck
    | FillProvince
    | DestroyProvince
    | DiscardProvince
    | CreateProvince
    | SetHonor
    | SpawnCard
    | RemoveCard
)


# Ownership gates — mirror of the ownership predicates in yasuki_gui/services/actions.py, kept in
# sync with it. Here the acting seat is explicit rather than read from a view's local_player, and a
# None owner means public.


def owns_card(state: TableState, seat: PlayerId, card_id: str) -> bool:
    """Return whether ``seat`` may act on the card. True for the card's owner and for public
    (owner-less) cards; False if the card is unknown or belongs to the other seat."""
    card = state.cards_by_id.get(card_id)
    if card is None:
        return False
    return card.owner is None or card.owner == seat


def owns_zone(state: TableState, seat: PlayerId, zone_key: ZoneKey) -> bool:
    """Return whether ``seat`` may act on the zone. True for the zone's owner and for public zones;
    False if the zone does not exist or belongs to the other seat."""
    zone = state.zones.get(zone_key)
    if zone is None:
        return False
    return zone.owner is None or zone.owner == seat


def owns_deck(state: TableState, seat: PlayerId, deck_key: DeckKey) -> bool:
    """Return whether ``seat`` owns the deck. Decks are always owned, so this is the key's owner;
    False if the deck does not exist."""
    if deck_key not in state.decks:
        return False
    return deck_key.owner == seat


def zone_owned_by_card(zone: Zone, card: L5RCard) -> bool:
    """Return whether the card and zone owners are compatible: True unless both are set and differ.
    Guards against placing one seat's card into the other seat's owned zone."""
    return zone.owner is None or card.owner is None or zone.owner == card.owner


def zone_accepts(zone: Zone, card: L5RCard) -> bool:
    """Return whether the card satisfies the zone's side and capacity constraints, without mutating.
    Mirrors the checks ``Zone.add`` makes before appending."""
    if zone.allowed_side is not None and card.side is not zone.allowed_side:
        return False
    return zone.has_capacity()


@dataclass(frozen=True, slots=True)
class Event:
    """A canonical record of one accepted mutation, for logging, redaction, and replay.

    Attributes
    ----------
    seq : int
        The table's version after the mutation; equals the prior ``seq`` for accepted read-only
        intents (``SEARCH_DECK``) that produce an event without changing state.
    seat : PlayerId
        The seat that acted.
    intent : Intent
        The fully resolved operation that occurred. For draws and province fills this is the
        ``MoveCard`` the server decided, not the originating ``Draw``/``FillProvince``.
    cards : tuple of str
        Ids of the cards whose state materially changed; the changed subset for batched flag ops.
    """

    seq: int
    seat: PlayerId
    intent: Intent
    cards: tuple[str, ...] = ()


def _remove_from_location(state: TableState, card: L5RCard) -> None:
    """Remove ``card`` (by identity) from whatever zone, deck, or the battlefield holds it, and drop
    any battlefield position."""
    for container in (*state.zones.values(), *state.decks.values(), state.battlefield):
        cards = container.cards
        for i, held in enumerate(cards):
            if held is card:
                del cards[i]
                state.positions.pop(card.id, None)
                return


def _move_card(state: TableState, seat: PlayerId, intent: MoveCard) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    dest = intent.to

    if dest == BATTLEFIELD:
        pos = intent.position or state.positions.get(card.id) or _DEFAULT_BOARD_POS
        _remove_from_location(state, card)
        state.battlefield.add(card)
        state.positions[card.id] = pos
        state.seq += 1
        return [Event(state.seq, seat, MoveCard(card.id, BATTLEFIELD, pos), (card.id,))]

    if isinstance(dest, DeckKey):
        if not owns_deck(state, seat, dest) or dest.side is not card.side:
            return []
        _remove_from_location(state, card)
        card.turn_face_down()
        card.unbow()
        card.uninvert()
        if intent.to_bottom:
            state.decks[dest].add_to_bottom([card])
        else:
            state.decks[dest].add_to_top([card])
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
    # Dropping a card onto the zone it already occupies — e.g. re-arranging within the hand — changes
    # nothing, so it produces no event and never reaches the log.
    if any(held is card for held in zone.cards):
        return []
    _remove_from_location(state, card)
    if dest.role is ZoneRole.HAND:
        # The hand is private by ownership (redaction hides it from the opponent regardless), so a
        # card enters it upright and face up — the owner reads their own hand, matching a fresh draw.
        card.turn_face_up()
        card.unbow()
        card.uninvert()
    elif dest.role is ZoneRole.PROVINCE:
        card.unbow()
    elif dest.role in (ZoneRole.FATE_DISCARD, ZoneRole.DYNASTY_DISCARD):
        # A discard pile is always public: a card landing there is revealed to both seats.
        card.turn_face_up()
    if dest.role is ZoneRole.HAND and intent.index is not None:
        # zone_accepts already gated the side and the hand has no capacity limit, so insert directly.
        zone.cards.insert(max(0, min(intent.index, len(zone.cards))), card)
    else:
        zone.add(card)
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest), (card.id,))]


def _move_deck_top(state: TableState, seat: PlayerId, intent: MoveDeckTop) -> list[Event]:
    # Source the deck's top card, then route it exactly like a MoveCard — the deck owner alone may
    # do this, and the card carries the owner's id so the delegated ownership gate passes.
    if not owns_deck(state, seat, intent.deck):
        return []
    cards = state.decks[intent.deck].cards
    if not cards:
        return []
    return _move_card(state, seat, MoveCard(cards[-1].id, intent.to, intent.position))


def _bring_to_top(state: TableState, card: L5RCard) -> None:
    """Move ``card`` to the end of the battlefield list (the top of the stack the client renders)."""
    cards = state.battlefield.cards
    for i, held in enumerate(cards):
        if held is card:
            if i != len(cards) - 1:
                cards.append(cards.pop(i))
            return


def _set_card_pos(state: TableState, seat: PlayerId, intent: SetCardPos) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    if not any(held is card for held in state.battlefield.cards):
        return []
    new_pos = BoardPos(intent.x, intent.y)
    if state.positions.get(card.id) == new_pos:
        return []
    state.positions[card.id] = new_pos
    # Moving a card on the battlefield also raises it to the top of the stack.
    _bring_to_top(state, card)
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
        new_pos = BoardPos(x, y)
        if state.positions.get(card.id) == new_pos:
            continue
        state.positions[card.id] = new_pos
        _bring_to_top(state, card)
        changed.append(card.id)
    if not changed:
        return []
    state.seq += 1
    return [Event(state.seq, seat, intent, tuple(changed))]


def _reorder_hand(state: TableState, seat: PlayerId, intent: ReorderHand) -> list[Event]:
    hand = state.zones.get(ZoneKey(seat, ZoneRole.HAND))
    if hand is None:
        return []
    cards = hand.cards
    current = next((i for i, held in enumerate(cards) if held.id == intent.card_id), None)
    if current is None:
        return []
    card = cards.pop(current)
    index = max(0, min(intent.index, len(cards)))
    cards.insert(index, card)
    if index == current:
        return []  # re-inserted at its own slot — the order is unchanged
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _raise(state: TableState, seat: PlayerId, intent: Raise) -> list[Event]:
    card = state.cards_by_id.get(intent.card_id)
    if card is None or not owns_card(state, seat, intent.card_id):
        return []
    cards = state.battlefield.cards
    if not cards or cards[-1] is card or not any(held is card for held in cards):
        return []
    _bring_to_top(state, card)
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
    card.flip()
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
    # Not owner-gated: any seat may peek any card. The card's peekers gain private sight; the public
    # log only reports that a peek happened.
    card = state.cards_by_id.get(intent.card_id)
    if card is None or seat in card.peekers:
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
    card = state.decks[intent.deck].draw_one()
    if card is None:
        return []
    if intent.deck.side is Side.FATE:
        card.turn_face_up()
        state.zones[ZoneKey(seat, ZoneRole.HAND)].add(card)
        dest: MoveDest = ZoneKey(seat, ZoneRole.HAND)
        position = None
    else:
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
            position = _UNPLACED_BOARD_POS
            state.positions[card.id] = position
    state.seq += 1
    return [Event(state.seq, seat, MoveCard(card.id, dest, position), (card.id,))]


def _shuffle(state: TableState, seat: PlayerId, intent: Shuffle) -> list[Event]:
    if not owns_deck(state, seat, intent.deck):
        return []
    state.decks[intent.deck].shuffle(seed=intent.seed)
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
    card = state.decks[DeckKey(seat, Side.DYNASTY)].draw_one()
    if card is None:
        return []
    card.unbow()
    card.turn_face_down()
    zone.add(card)
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
    discard = state.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)]
    moved = []
    while zone.cards:
        card = zone.cards.pop()
        card.turn_face_up()
        discard.add(card)
        moved.append(card.id)
    del state.zones[intent.zone]
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
    if not zone.cards:
        return []
    card = zone.cards.pop()
    card.turn_face_up()
    state.zones[ZoneKey(seat, ZoneRole.DYNASTY_DISCARD)].add(card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _create_province(state: TableState, seat: PlayerId, intent: CreateProvince) -> list[Event]:
    idx = 0
    while ZoneKey(seat, ZoneRole.PROVINCE, idx) in state.zones:
        idx += 1
    state.zones[ZoneKey(seat, ZoneRole.PROVINCE, idx)] = ProvinceZone(owner=seat)
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _set_honor(state: TableState, seat: PlayerId, intent: SetHonor) -> list[Event]:
    seat_info = state.seats[seat]
    new_honor = seat_info.honor + intent.delta if intent.delta is not None else intent.value
    if new_honor == seat_info.honor:
        return []
    seat_info.honor = new_honor
    state.seq += 1
    return [Event(state.seq, seat, intent)]


def _spawn_card(state: TableState, seat: PlayerId, intent: SpawnCard) -> list[Event]:
    if intent.card_id in state.cards_by_id:
        return []
    card = L5RCard(
        id=intent.card_id,
        name=intent.name,
        side=intent.side,
        owner=None,
        face_up=True,
        image_front=Path(intent.image) if intent.image else None,
        is_token=True,
    )
    state.cards_by_id[card.id] = card
    state.battlefield.add(card)
    state.positions[card.id] = intent.position
    state.seq += 1
    return [Event(state.seq, seat, intent, (card.id,))]


def _remove_card(state: TableState, seat: PlayerId, intent: RemoveCard) -> list[Event]:
    if not owns_card(state, seat, intent.card_id):
        return []
    card = state.cards_by_id[intent.card_id]
    # Only spawned tokens may leave the table outright; a real card from a deck or zone is never
    # destroyable — it must be moved to a discard or banish instead.
    if not card.is_token:
        return []
    del state.cards_by_id[intent.card_id]
    _remove_from_location(state, card)
    state.seq += 1
    return [Event(state.seq, seat, intent, (intent.card_id,))]


_HANDLERS = {
    IntentOp.MOVE_CARD: _move_card,
    IntentOp.MOVE_DECK_TOP: _move_deck_top,
    IntentOp.SET_CARD_POS: _set_card_pos,
    IntentOp.SET_CARD_POSITIONS: _set_card_positions,
    IntentOp.REORDER_HAND: _reorder_hand,
    IntentOp.RAISE: _raise,
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
}


def apply_intent(state: TableState, seat: PlayerId, intent: Intent) -> list[Event]:
    """Validate and apply one intent, mutating ``state`` in place and returning the events produced.

    Pure apart from the in-place mutation: no I/O, deterministic given the state, seat, and intent
    (shuffles derive their order from the intent's explicit seed). Ownership, side, and capacity
    violations are rejected and leave the state untouched, returning an empty list; ``seq`` advances
    only when the table actually changes.

    Parameters
    ----------
    state : TableState
        The authoritative table; mutated in place on an accepted intent.
    seat : PlayerId
        The seat attempting the action.
    intent : Intent
        The operation to apply.
    """
    return _HANDLERS[intent.op](state, seat, intent)
