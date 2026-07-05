from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Counter:
    """A kind of counter a card can carry — a scalar tally whose stat modifiers apply per count.
    Data, not behavior: the effect layer reads these fields; the counter never acts. Each field is a
    per-count stat modifier defaulting to 0, so a counter lists only what it changes."""

    key: str
    gold_production: int = 0


# Raises the host's Gold Production by one per token (the "+1GP Wealth token").
WEALTH = Counter("wealth", gold_production=1)

ALL_COUNTERS: tuple[Counter, ...] = (WEALTH,)
_BY_KEY = {counter.key: counter for counter in ALL_COUNTERS}


def counter_from_key(key: str) -> Counter:
    """The registered counter for ``key``. Raise ``KeyError`` on an unknown key, so a malformed
    intent is rejected rather than minting a novel counter."""
    return _BY_KEY[key]
