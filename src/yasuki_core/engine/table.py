from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple, Literal, Final
from collections.abc import Iterator

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.zones import (
    Zone,
    HandZone,
    BattlefieldZone,
    FateDiscardZone,
    FateBanishZone,
    DynastyDiscardZone,
    DynastyBanishZone,
    ProvinceZone,
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
    avatar: dict | None = None  # the user's avatar spec; None falls back to the name's initials


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
    attachments : dict mapping str to (str or ZoneKey)
        The attachment graph, keyed by the attached (child) card id. A value is either a parent card
        id — the child sits behind that battlefield card — or a province ``ZoneKey`` a fortification
        or region is attached to. Only battlefield cards appear as children; a card leaving the
        battlefield drops its entry and detaches whatever is hung off it.
    cards_by_id : dict mapping str to L5RCard
        Identity map over every card on the table, for fast intent lookup.
    seq : int
        Monotonic view version, bumped on every state change: by ``apply_intent`` for game intents
        and by :meth:`bump_version` for non-intent seat metadata, so no two distinct broadcasts share
        a ``seq``. The action log records only intents, so logged ``seq`` values may skip the bumps.
    """

    seats: dict[PlayerId, SeatInfo]
    zones: dict[ZoneKey, Zone]
    decks: dict[DeckKey, Deck]
    battlefield: BattlefieldZone
    # L5RCard is frozen, so battlefield positions live here, keyed by card id, not on the card.
    positions: dict[str, BoardPos] = field(default_factory=dict)
    # The child->parent attachment graph, external to the frozen card. See the class docstring.
    attachments: dict[str, "AttachTarget"] = field(default_factory=dict)
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

    def bump_version(self) -> None:
        """Advance :attr:`seq` for a state change made outside ``apply_intent`` (seat metadata), so
        every broadcast that changed the view carries a strictly newer ``seq`` than the last."""
        self.seq += 1

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

        for child_id, target in self.attachments.items():
            if child_id not in battlefield_ids:
                raise ValueError(f"attachment child not on battlefield: {child_id!r}")
            if isinstance(target, ZoneKey):
                if not isinstance(self.zones.get(target), ProvinceZone):
                    raise ValueError(f"attachment references missing province: {target}")
            elif target not in battlefield_ids:
                raise ValueError(f"attachment references non-battlefield card: {target!r}")
        # No card-to-card cycles: walking parents from any child must terminate.
        for start in self.attachments:
            seen = {start}
            cursor = self.attachments.get(start)
            while isinstance(cursor, str):
                if cursor in seen:
                    raise ValueError(f"attachment cycle involving {start!r}")
                seen.add(cursor)
                cursor = self.attachments.get(cursor)

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


# Sentinel destination for the shared battlefield in MOVE_CARD, distinct from any owned ZoneKey or
# DeckKey. A card moved here also carries a BoardPos.
BATTLEFIELD: Final = "battlefield"

# Where a card lands on the battlefield when no position is supplied.
DEFAULT_BOARD_POS: Final = BoardPos(0.0, 0.0)

# A dynasty card drawn while every province is full lands here: a negative sentinel the client
# recognises and lays out next to the owner's dynasty deck, like an unplaced pre-game permanent.
UNPLACED_BOARD_POS: Final = BoardPos(-1.0, -1.0)

MoveDest = ZoneKey | DeckKey | Literal["battlefield"]

# What a card may be attached to: another battlefield card (by id) or a province zone.
AttachTarget = str | ZoneKey


# Ownership and zone predicates — pure read-only queries on the table, shared by the manual sim
# (intents.py) and the rules engine. A None owner means public (any seat may act).


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
