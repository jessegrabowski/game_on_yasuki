from dataclasses import dataclass
from pathlib import Path
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.paths import DEFAULT_STRONGHOLD, DEFAULT_SENSEI, DEFAULT_WIND


@dataclass(frozen=True, slots=True)
class StrongholdCard(L5RCard):
    """A stronghold, placed face-up at setup; ``starting_honor`` is the honor the player begins
    the game with and ``starting_hand_size`` is the number of fate cards drawn into the opening
    hand."""

    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0
    province_count: int = 4
    starting_hand_size: int = 5
    image_front: Path | None = DEFAULT_STRONGHOLD


@dataclass(frozen=True, slots=True)
class SenseiCard(L5RCard):
    """An optional sensei, placed face-up alongside the stronghold at setup. Its ``starting_honor``,
    ``gold_production``, and ``province_strength`` are deltas folded into the stronghold's
    characteristics at setup."""

    starting_honor: int = 0
    gold_production: int = 0
    province_strength: int = 0
    image_front: Path | None = DEFAULT_SENSEI


@dataclass(frozen=True, slots=True)
class WindCard(L5RCard):
    """An optional wind, a pre-game permanent placed face-up at setup."""

    image_front: Path | None = DEFAULT_WIND
