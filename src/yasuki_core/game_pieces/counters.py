from dataclasses import dataclass

import yaml

from yasuki_core.paths import DATABASE_DIR


@dataclass(frozen=True, slots=True)
class Counter:
    """A kind of counter a card can carry — a scalar tally whose stat modifiers apply per count.
    Data, not behavior: the effect layer reads the delta fields; the counter never acts. Each stat
    field is a per-count modifier defaulting to 0, so a counter lists only what it changes. The field
    names match ``Stat.value`` strings so the effect layer can bridge them generically."""

    key: str
    name: str = ""
    force: int = 0
    chi: int = 0
    gold_production: int = 0
    province_strength: int = 0
    personal_honor: int = 0


_CATALOG_PATH = DATABASE_DIR / "counters.yaml"


def _load_catalog() -> tuple[Counter, ...]:
    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8"))
    counters = tuple(Counter(**entry) for entry in data["counters"])
    if len({counter.key for counter in counters}) != len(counters):
        raise ValueError("counters.yaml has duplicate keys")
    return counters


# The full counter vocabulary, loaded from the same catalogue the database `counters` table uses.
ALL_COUNTERS: tuple[Counter, ...] = _load_catalog()
_BY_KEY = {counter.key: counter for counter in ALL_COUNTERS}

# Named handles for the counters the rules engine references directly (triggers, abilities, flow).
WEALTH = _BY_KEY["wealth"]
SINCERITY = _BY_KEY["sincerity"]


def counter_from_key(key: str) -> Counter:
    """The registered counter for ``key``. Raise ``KeyError`` on an unknown key, so a malformed
    intent is rejected rather than minting a novel counter."""
    return _BY_KEY[key]
