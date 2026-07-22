import pytest

from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.game_pieces.counters import (
    ALL_COUNTERS,
    SINCERITY,
    WEALTH,
    Counter,
    counter_from_key,
)


def test_catalog_loads_with_unique_keys():
    keys = [counter.key for counter in ALL_COUNTERS]
    assert len(keys) == len(set(keys))


def test_named_handles_resolve_from_the_catalog():
    assert WEALTH is counter_from_key("wealth")
    assert SINCERITY is counter_from_key("sincerity")
    assert WEALTH.gold_production == 1  # the stat the effect layer reads
    assert SINCERITY.gold_production == 0


def test_a_stat_delta_counter_carries_its_deltas():
    fire = counter_from_key("fire")
    assert fire.force == 1 and fire.chi == 0
    plus1f_plus1c_plus1ph = counter_from_key("plus1f_plus1c_plus1ph")
    assert (plus1f_plus1c_plus1ph.force, plus1f_plus1c_plus1ph.chi) == (1, 1)
    assert plus1f_plus1c_plus1ph.personal_honor == 1


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        counter_from_key("not_a_counter")


def test_counter_has_a_field_for_every_bridged_stat():
    # active_modifiers reads deltas via getattr(counter, stat.value); every Stat must map to a field.
    for stat in Stat:
        assert hasattr(Counter("k"), stat.value)
