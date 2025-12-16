from dataclasses import dataclass
from pathlib import Path
from app.game_pieces.cards import L5RCard
from app.paths import (
    DYNASTY_BACK,
    DEFAULT_PERSONALITY,
    DEFAULT_HOLDING,
    DEFAULT_EVENT,
    DEFAULT_REGION,
    DEFAULT_CELESTIAL,
)


@dataclass(frozen=True, slots=True)
class DynastyCard(L5RCard):
    gold_cost: int | None = None
    image_back: Path | None = DYNASTY_BACK


@dataclass(frozen=True, slots=True)
class DynastyPersonality(DynastyCard):
    force: int = 0
    chi: int = 0
    personal_honor: int = 0
    image_front: Path | None = DEFAULT_PERSONALITY


@dataclass(frozen=True, slots=True)
class DynastyHolding(DynastyCard):
    gold_production: int = 0
    image_front: Path | None = DEFAULT_HOLDING


@dataclass(frozen=True, slots=True)
class DynastyEvent(DynastyCard):
    image_front: Path | None = DEFAULT_EVENT


@dataclass(frozen=True, slots=True)
class DynastyRegion(DynastyCard):
    image_front: Path | None = DEFAULT_REGION


@dataclass(frozen=True, slots=True)
class DynastyCelestial(DynastyCard):
    image_front: Path | None = DEFAULT_CELESTIAL
