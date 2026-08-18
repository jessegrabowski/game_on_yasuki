from dataclasses import dataclass, field
from pathlib import Path

from yasuki_core.game_pieces.constants import AttachmentType, Element, Side, Timing
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

    A print is frozen and never mutated, so copies may share one — a change to one card in play
    must not reach another. The subclasses carry the printed stats, and which subclass a print is
    is what gives a card in play its type.

    "Resolved deck entry" rather than "database row" is deliberate. Which printing's art a card
    wears and which deck section it was filed under are chosen per entry, so two decks naming the
    same card get their own prints.
    """

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


@dataclass(frozen=True, slots=True)
class DynastyPrint(CardPrint):
    gold_cost: int | None = None
    image_back: Path | None = DYNASTY_BACK


@dataclass(frozen=True, slots=True)
class PersonalityPrint(DynastyPrint):
    image_front: Path | None = DEFAULT_PERSONALITY
    force: int = 0
    chi: int = 0
    personal_honor: int = 0
    # None is the printed dash: below any number, so the card recruits at any Family Honor.
    honor_requirement: int | None = None
    # How many Weapon Items may hang on him (CR, Weapon). One is the rulebook's default rather than
    # anything a card prints, and it sits here so the limit reads like any other characteristic —
    # Kensai raises it with a modifier instead of exempting him from a rule.
    weapon_limit: int = 1


@dataclass(frozen=True, slots=True)
class HoldingPrint(DynastyPrint):
    image_front: Path | None = DEFAULT_HOLDING
    gold_production: int = 0


@dataclass(frozen=True, slots=True)
class EventPrint(DynastyPrint):
    image_front: Path | None = DEFAULT_EVENT


@dataclass(frozen=True, slots=True)
class RegionPrint(DynastyPrint):
    image_front: Path | None = DEFAULT_REGION


@dataclass(frozen=True, slots=True)
class CelestialPrint(DynastyPrint):
    image_front: Path | None = DEFAULT_CELESTIAL


@dataclass(frozen=True, slots=True)
class FatePrint(CardPrint):
    focus: int | None = None
    gold_cost: int | None = None
    image_back: Path | None = FATE_BACK


@dataclass(frozen=True, slots=True)
class ActionPrint(FatePrint):
    image_front: Path | None = DEFAULT_STRATEGY
    timings: tuple[Timing, ...] = ()

    def __post_init__(self):
        CardPrint.__post_init__(self)
        if not isinstance(self.timings, tuple):
            object.__setattr__(self, "timings", tuple(self.timings))


@dataclass(frozen=True, slots=True)
class AttachmentPrint(FatePrint):
    image_front: Path | None = DEFAULT_ITEM
    attachment_type: AttachmentType = AttachmentType.ITEM
    attach_restrictions: tuple[str, ...] = ()
    # What the card brings to the unit it joins, against what it hands the Personality. A Follower
    # stands in the unit and so has a Force of its own, but no Chi; an Item or Spell has neither, and
    # both of its numbers are modifiers. Shadowlands Ambassador does both — Force 2 to the unit, -1
    # Chi to the Personality — so these are separate fields rather than one number.
    force: int = 0
    chi: int = 0
    force_modifier: int = 0
    chi_modifier: int = 0

    def __post_init__(self):
        CardPrint.__post_init__(self)
        if not isinstance(self.attach_restrictions, tuple):
            object.__setattr__(self, "attach_restrictions", tuple(self.attach_restrictions))


@dataclass(frozen=True, slots=True)
class RingPrint(FatePrint):
    image_front: Path | None = DEFAULT_RING
    element: Element = Element.VOID


@dataclass(frozen=True, slots=True)
class AncestorPrint(FatePrint):
    pass


@dataclass(frozen=True, slots=True)
class StrongholdPrint(CardPrint):
    image_front: Path | None = DEFAULT_STRONGHOLD
    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0
    province_count: int = 4
    starting_hand_size: int = 5


@dataclass(frozen=True, slots=True)
class SenseiPrint(CardPrint):
    image_front: Path | None = DEFAULT_SENSEI
    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0


@dataclass(frozen=True, slots=True)
class WindPrint(CardPrint):
    image_front: Path | None = DEFAULT_WIND
