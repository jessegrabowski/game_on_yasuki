import pytest

from yasuki_core.engine.rules import triggers


@pytest.fixture
def reacting():
    """Register triggers for one test and clear them afterwards.

    `_TRIGGERS` is module-global and appends, so a leaked registration fires in every later test in
    the process. The fixture owns that hygiene; each test still writes its own reaction inline.
    """
    registered: list[tuple[type, str]] = []

    def _register(event: type, printed_id: str, trigger):
        triggers.on(event, printed_id)(trigger)
        registered.append((event, printed_id))

    yield _register
    for event, printed_id in registered:
        triggers._TRIGGERS[event].pop(printed_id, None)
