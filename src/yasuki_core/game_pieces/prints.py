from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import ClassVar

from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Element, Side, Timing
from yasuki_core.game_pieces.dynasty import (
    DynastyCard,
    DynastyCelestial,
    DynastyEvent,
    DynastyHolding,
    DynastyPersonality,
    DynastyRegion,
)
from yasuki_core.game_pieces.fate import (
    FateAction,
    FateAncestor,
    FateAttachment,
    FateCard,
    FateRing,
)
from yasuki_core.game_pieces.pregame import SenseiCard, StrongholdCard, WindCard
from yasuki_core.paths import (
    DEFAULT_CELESTIAL,
    DEFAULT_EVENT,
    DEFAULT_HOLDING,
    DEFAULT_ITEM,
    DEFAULT_PERSONALITY,
    DEFAULT_REGION,
    DEFAULT_RING,
    DEFAULT_SENSEI,
    DEFAULT_STRATEGY,
    DEFAULT_STRONGHOLD,
    DEFAULT_WIND,
    DYNASTY_BACK,
    FATE_BACK,
)


@dataclass(frozen=True, slots=True)
class CardPrint:
    """A printed card: everything identical on every copy of it.

    One is built per resolved deck entry and shared by every copy that entry produces, so it is
    never mutated — a change to one copy in play must not reach another. The subclasses carry the
    printed stats and mirror the card classes they describe.

    "Resolved deck entry" rather than "database row" is deliberate. Which printing's art a card
    wears and which deck section it was filed under are chosen per entry, so two decks naming the
    same card get their own prints.
    """

    CARD: ClassVar[type] = L5RCard

    name: str
    side: Side
    # The stable printed identity — the database card slug, shared by every copy and printing.
    # Per-card effect handlers key off it; None for fabricated demo cards and spawned tokens.
    printed_id: str | None = None
    clan: str | None = None
    clans: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    traits: tuple[str, ...] = ()
    card_type: str | None = None
    creates: tuple[str, ...] = ()
    text: str = ""
    is_unique: bool = False
    image_front: Path | None = None
    image_back: Path | None = None
    # The other face of a double-faced card, by printed id. Which face a copy presents belongs to
    # the copy, not to the print.
    back_card_id: str | None = None
    # Client-render metadata for a deck entry that borrows another printing's art, so it stays out
    # of identity the way it does on the card.
    art_swap: dict | None = field(default=None, compare=False)

    def __post_init__(self):
        for name in ("clans", "keywords", "traits", "creates"):
            value = getattr(self, name)
            if not isinstance(value, tuple):
                object.__setattr__(self, name, tuple(value))

    def as_card_fields(self) -> dict:
        """This print's characteristics as the keyword arguments a card class takes for them."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


@dataclass(frozen=True, slots=True)
class DynastyPrint(CardPrint):
    CARD: ClassVar[type] = DynastyCard

    gold_cost: int | None = None
    image_back: Path | None = DYNASTY_BACK


@dataclass(frozen=True, slots=True)
class PersonalityPrint(DynastyPrint):
    CARD: ClassVar[type] = DynastyPersonality

    image_front: Path | None = DEFAULT_PERSONALITY
    force: int = 0
    chi: int = 0
    personal_honor: int = 0
    # None is the printed dash: below any number, so the card recruits at any Family Honor.
    honor_requirement: int | None = None


@dataclass(frozen=True, slots=True)
class HoldingPrint(DynastyPrint):
    CARD: ClassVar[type] = DynastyHolding

    image_front: Path | None = DEFAULT_HOLDING
    gold_production: int = 0


@dataclass(frozen=True, slots=True)
class EventPrint(DynastyPrint):
    CARD: ClassVar[type] = DynastyEvent

    image_front: Path | None = DEFAULT_EVENT


@dataclass(frozen=True, slots=True)
class RegionPrint(DynastyPrint):
    CARD: ClassVar[type] = DynastyRegion

    image_front: Path | None = DEFAULT_REGION


@dataclass(frozen=True, slots=True)
class CelestialPrint(DynastyPrint):
    CARD: ClassVar[type] = DynastyCelestial

    image_front: Path | None = DEFAULT_CELESTIAL


@dataclass(frozen=True, slots=True)
class FatePrint(CardPrint):
    CARD: ClassVar[type] = FateCard

    focus: int | None = None
    gold_cost: int | None = None
    image_back: Path | None = FATE_BACK


@dataclass(frozen=True, slots=True)
class ActionPrint(FatePrint):
    CARD: ClassVar[type] = FateAction

    image_front: Path | None = DEFAULT_STRATEGY
    timings: tuple[Timing, ...] = ()

    def __post_init__(self):
        CardPrint.__post_init__(self)
        if not isinstance(self.timings, tuple):
            object.__setattr__(self, "timings", tuple(self.timings))


@dataclass(frozen=True, slots=True)
class AttachmentPrint(FatePrint):
    CARD: ClassVar[type] = FateAttachment

    image_front: Path | None = DEFAULT_ITEM
    attachment_type: AttachmentType = AttachmentType.ITEM
    attach_restrictions: tuple[str, ...] = ()

    def __post_init__(self):
        CardPrint.__post_init__(self)
        if not isinstance(self.attach_restrictions, tuple):
            object.__setattr__(self, "attach_restrictions", tuple(self.attach_restrictions))


@dataclass(frozen=True, slots=True)
class RingPrint(FatePrint):
    CARD: ClassVar[type] = FateRing

    image_front: Path | None = DEFAULT_RING
    element: Element = Element.VOID


@dataclass(frozen=True, slots=True)
class AncestorPrint(FatePrint):
    CARD: ClassVar[type] = FateAncestor


@dataclass(frozen=True, slots=True)
class StrongholdPrint(CardPrint):
    CARD: ClassVar[type] = StrongholdCard

    image_front: Path | None = DEFAULT_STRONGHOLD
    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0
    province_count: int = 4
    starting_hand_size: int = 5


@dataclass(frozen=True, slots=True)
class SenseiPrint(CardPrint):
    CARD: ClassVar[type] = SenseiCard

    image_front: Path | None = DEFAULT_SENSEI
    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0


@dataclass(frozen=True, slots=True)
class WindPrint(CardPrint):
    CARD: ClassVar[type] = WindCard

    image_front: Path | None = DEFAULT_WIND
