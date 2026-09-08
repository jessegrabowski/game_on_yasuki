from yasuki_core.engine.rules.registrar import CARD_REGISTRIES, HandlerRegistry


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
