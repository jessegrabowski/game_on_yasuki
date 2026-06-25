from dataclasses import dataclass
from pathlib import Path
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.paths import DEFAULT_STRONGHOLD, DEFAULT_SENSEI, DEFAULT_WIND


@dataclass(frozen=True, slots=True)
class StrongholdCard(L5RCard):
    """A stronghold, placed face-up at setup; ``starting_honor`` is the honor the player begins
    the game with."""

    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0
    image_front: Path | None = DEFAULT_STRONGHOLD


@dataclass(frozen=True, slots=True)
class SenseiCard(L5RCard):
    """An optional sensei, placed face-up alongside the stronghold at setup; its ``starting_honor``
    is added to the stronghold's."""

    starting_honor: int = 0
    image_front: Path | None = DEFAULT_SENSEI


@dataclass(frozen=True, slots=True)
class WindCard(L5RCard):
    """An optional wind, a pre-game permanent placed face-up at setup."""

    image_front: Path | None = DEFAULT_WIND
