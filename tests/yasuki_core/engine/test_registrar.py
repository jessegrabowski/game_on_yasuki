import pytest

from yasuki_core.engine.registrar import CARD_REGISTRIES, FlagRegistry, HandlerRegistry

# Without this the catalogue holds only what this file's imports happen to reach.
from yasuki_core.engine.rules import cards  # noqa: F401


@pytest.mark.parametrize("built", CARD_REGISTRIES, ids=lambda built: built.label)
def test_every_registry_refuses_a_second_registration_for_one_card(built):
    """The guard that makes a duplicate loud. A card registered from two set modules is a real
    mistake, and a plain dict or set would absorb it silently -- the second handler shadowing the
    first, or the second flag doing nothing at all."""
    record = (
        built.make_register()
        if isinstance(built, FlagRegistry)
        else (lambda printed_id: built.make_decorator()(printed_id)(lambda *args: None))
    )
    record("guard_probe")

    try:
        with pytest.raises(ValueError, match=f"guard_probe {built.complaint}"):
            record("guard_probe")
    finally:
        if isinstance(built, FlagRegistry):
            built.discard("guard_probe")
        else:
            built.pop("guard_probe")


def test_a_registry_joins_the_catalogue_when_it_is_built():
    # The catalogue is what validation reads instead of a hand-kept list, so a registry that does
    # not join it is a registry nothing checks.
    before = len(CARD_REGISTRIES)
    probe: HandlerRegistry[object] = HandlerRegistry("probe", "already probed")

    try:
        assert CARD_REGISTRIES[before:] == [probe]
    finally:
        CARD_REGISTRIES.remove(probe)


def test_the_decorator_hands_back_the_function_it_recorded():
    # A decorator that returned None would silently replace every registered handler with None at
    # import time, and the card would look registered.
    registry: HandlerRegistry[object] = HandlerRegistry("probe", "already probed")
    handler = object()

    try:
        assert registry.make_decorator()("probe_card")(handler) is handler
        assert registry["probe_card"] is handler
    finally:
        CARD_REGISTRIES.remove(registry)
