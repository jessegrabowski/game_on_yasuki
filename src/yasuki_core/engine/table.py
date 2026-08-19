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
from yasuki_core.game_pieces.prints import CardPrint, PersonalityPrint


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

    @property
    def token(self) -> str:
        """A string naming this zone, for the places that carry one beside card ids — a decision's
        candidates are strings, and a Province is chosen as a slot rather than as the card in it."""
        return f"{self.owner.name}:{self.role.value}:{'' if self.idx is None else self.idx}"

    @classmethod
    def from_token(cls, token: str) -> "ZoneKey":
        """The zone :attr:`token` names. Raise ``ValueError`` if it names none."""
        owner, role, idx = token.split(":")
        return cls(PlayerId[owner], ZoneRole(role), int(idx) if idx else None)


class DeckKey(NamedTuple):
    owner: PlayerId
    side: Side  # FATE or DYNASTY


class Location(NamedTuple):
    """Where a card in play stands: in a seat's home, or at a battlefield.

    The rules' answer to "where is this card", as against :class:`BoardPos`, which is a table
    coordinate a player may drag a card to and means nothing to the rules.

    Exactly one field is set. Build the two shapes with :meth:`home` and :meth:`at_battlefield`
    rather than by hand, and ask which one you hold with :attr:`is_home`.

    Attributes
    ----------
    seat : PlayerId, optional
        The seat whose home the card stands in. None at a battlefield.
    battlefield : int, optional
        The index of the battlefield the card stands at, matching its position in the attack's
        battlefield tuple. None at home.
    """

    seat: PlayerId | None = None
    battlefield: int | None = None

    @classmethod
    def home(cls, seat: PlayerId) -> "Location":
        """The home of ``seat``."""
        return cls(seat=seat)

    @classmethod
    def at_battlefield(cls, index: int) -> "Location":
        """The battlefield at ``index``."""
        return cls(battlefield=index)

    @property
    def is_home(self) -> bool:
        """Whether this is a home rather than a battlefield."""
        return self.battlefield is None

    def is_well_formed(self) -> bool:
        """Whether exactly one of the two fields is set, which every stored location must be."""
        return (self.seat is None) != (self.battlefield is None)


class BoardPos(NamedTuple):
    x: float
    y: float


@dataclass(slots=True)
class SeatInfo:
    name: str
    honor: int = 0  # set from the stronghold + sensei at setup; 0 until then
    # Whether this seat waives every Personality's Honor Requirement when recruiting. Granted by
    # cards' effects; false until one sets it.
    ignores_honor_requirements: bool = False
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
    locations : dict mapping str to Location
        Where each card in play stands — a seat's home, or a battlefield — keyed by card id. Unlike
        ``positions`` this is rules truth, not presentation. Partial: a card with no entry is at its
        owner's home, which :func:`location_of` supplies, so a board on which nothing has ever
        assigned carries an empty map.
    attachments : dict mapping str to (str or ZoneKey)
        Which card or province a card sits behind on the table, keyed by the card on top. This is
        presentation, not rules: the manual sandbox lets a player stack anything on anything, so a
        Follower parked behind a Stronghold is a legal entry here and means nothing to the rules
        layer, which never reads it. Only battlefield cards appear as children; a card leaving the
        battlefield drops its entry and unstacks whatever sits on it.
    units : dict mapping str to str
        Unit membership, keyed by the attached card id and naming the Personality it is attached to.
        A Personality together with the cards attached to him makes up a unit (CR, Unit), and
        attachments are the only card type that may attach to a Personality — so unlike
        ``attachments`` this relation is flat, and a parent is always a Personality.
    province_attachments : dict mapping str to ZoneKey
        The Regions and Fortifications attached to a province, keyed by card id. A separate relation
        from ``units`` because it is a separate relation in the rules: nothing attaches to both, and
        one map holding either would be unable to say so.
    province_counters : dict mapping ZoneKey to a dict of str to int
        Counters resting on a Province rather than on a card, keyed by the Province's zone key. A
        Province is a slot rather than a card, so a "+1 strength Wall token" has nowhere else to
        live — the card sitting in the slot is refilled and destroyed independently of it.
    cards_by_id : dict mapping str to L5RCard
        Identity map over every card on the table, for fast intent lookup.
    creatable_tokens : dict mapping str to CardPrint
        Token templates the loaded decks can create, keyed by token card id, resolved at deck load.
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
    # Rules truth about where a card in play stands, and partial: absent means "at its owner's
    # home". See the class docstring, and read it through location_of rather than directly.
    locations: dict[str, Location] = field(default_factory=dict)
    # Presentation stacking, external to the frozen card. See the class docstring.
    attachments: dict[str, "AttachTarget"] = field(default_factory=dict)
    # The two rules relations. Kept apart because they are apart in the rules — one map with a
    # `str | ZoneKey` value cannot express that a Follower may never be a parent.
    units: dict[str, str] = field(default_factory=dict)
    province_attachments: dict[str, ZoneKey] = field(default_factory=dict)
    province_counters: dict["ZoneKey", dict[str, int]] = field(default_factory=dict)
    cards_by_id: dict[str, L5RCard] = field(default_factory=dict)
    # A SpawnCard naming a token_id copies the matching template onto the battlefield, so spawning a
    # creatable token needs no live database call.
    creatable_tokens: dict[str, CardPrint] = field(default_factory=dict)
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
        exactly the located cards, that battlefield positions and locations reference only
        battlefield cards, that every stored location names either a home or a battlefield, and that
        every zone and deck key is well-formed (known owner, province-only ``idx``, matching zone
        owner, fate/dynasty deck side).
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

        stray_locations = set(self.locations) - battlefield_ids
        if stray_locations:
            raise ValueError(f"locations reference cards not in play: {sorted(stray_locations)}")
        for card_id, location in self.locations.items():
            if not location.is_well_formed():
                raise ValueError(f"location for {card_id!r} names neither a home nor a battlefield")
            if location.seat is not None and location.seat not in self.seats:
                raise ValueError(f"location for {card_id!r} has unknown seat: {location.seat}")

        for child_id, target in self.attachments.items():
            if child_id not in battlefield_ids:
                raise ValueError(f"attachment child not on battlefield: {child_id!r}")
            if isinstance(target, ZoneKey):
                if not isinstance(self.zones.get(target), ProvinceZone):
                    raise ValueError(f"attachment references missing province: {target}")
            elif target not in battlefield_ids:
                raise ValueError(f"attachment references non-battlefield card: {target!r}")
        # No card-to-card cycles: walking parents from any child must terminate. Only the stacking
        # relation can chain, so only it can loop.
        for start in self.attachments:
            seen = {start}
            cursor = self.attachments.get(start)
            while isinstance(cursor, str):
                if cursor in seen:
                    raise ValueError(f"attachment cycle involving {start!r}")
                seen.add(cursor)
                cursor = self.attachments.get(cursor)

        for card_id, personality_id in self.units.items():
            if card_id not in battlefield_ids:
                raise ValueError(f"unit member not on battlefield: {card_id!r}")
            if personality_id not in battlefield_ids:
                raise ValueError(f"unit references non-battlefield Personality: {personality_id!r}")
            if not isinstance(self.cards_by_id[personality_id].printed, PersonalityPrint):
                raise ValueError(f"unit parent is not a Personality: {personality_id!r}")
            if card_id in self.province_attachments:
                raise ValueError(f"card is in a unit and on a province: {card_id!r}")

        for card_id, zone_key in self.province_attachments.items():
            if card_id not in battlefield_ids:
                raise ValueError(f"province attachment not on battlefield: {card_id!r}")
            if not isinstance(self.zones.get(zone_key), ProvinceZone):
                raise ValueError(f"province attachment references missing province: {zone_key}")

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


# Ownership, zone and location predicates — pure read-only queries on the table, shared by the
# manual sim (intents.py) and the rules engine. A None owner means public (any seat may act).


def location_of(state: TableState, card: L5RCard) -> Location:
    """Where ``card`` stands, supplying its owner's home when the table records nothing.

    Read locations through this rather than off ``state.locations``, which is partial. Home is the
    owner's until the engine models control separately from ownership.
    """
    recorded = state.locations.get(card.id)
    return Location.home(card.owner) if recorded is None else recorded


def unit_members(state: TableState, card: L5RCard) -> list[L5RCard]:
    """``card`` and every card attached to it, the Personality first.

    A Personality together with the cards attached to him makes up a unit (CR, Unit); a card with
    nothing attached is a unit of one, so this answers for any card, not only a Personality.
    """
    members = [card]
    members.extend(
        state.cards_by_id[member_id]
        for member_id, personality_id in state.units.items()
        if personality_id == card.id
    )
    return members


def owns_card(state: TableState, seat: PlayerId, card_id: str) -> bool:
    """Return whether ``seat`` may act on the card: True for its owner, False if the card is unknown
    or belongs to the other seat."""
    card = state.cards_by_id.get(card_id)
    if card is None:
        return False
    return card.owner == seat


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
    """Return whether the card may sit in the zone: True for a public zone or the card owner's own.
    Guards against placing one seat's card into the other seat's owned zone."""
    return zone.owner is None or zone.owner == card.owner


def zone_accepts(zone: Zone, card: L5RCard) -> bool:
    """Return whether the card satisfies the zone's side and capacity constraints, without mutating.
    Mirrors the checks ``Zone.add`` makes before appending."""
    if zone.allowed_side is not None and card.side is not zone.allowed_side:
        return False
    return zone.has_capacity()
