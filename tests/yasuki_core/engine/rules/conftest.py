from contextlib import contextmanager

import pytest

from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.model import Ability
from yasuki_core.engine.rules.vocabulary.locations import CardLocation
from yasuki_core.engine.rules.abilities.registry import _ABILITIES, register_ability


@pytest.fixture
def reacting():
    """Register triggers for one test and clear them afterwards.

    `_TRIGGERS` is module-global and appends, so a leaked registration fires in every later test in
    the process. The fixture owns that hygiene. Each test still writes its own reaction inline.
    """
    registered: list[tuple[type, str]] = []

    def _register(
        event: type,
        printed_id: str,
        trigger,
        *,
        where: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,),
        ruleset: str | None = None,
    ):
        triggers.on(event, printed_id, where=where, ruleset=ruleset)(trigger)
        registered.append((event, printed_id))

    yield _register
    for event, printed_id in registered:
        for by_card in triggers._TRIGGERS.get(event, {}).values():
            by_card.pop(printed_id, None)


@pytest.fixture
def watching():
    """Register condition watches for one test and clear them afterwards, for the reason
    ``reacting`` gives."""
    registered: list[str] = []

    def _register(
        printed_id: str,
        condition,
        reaction,
        *,
        key: str = "probe",
        where: tuple[CardLocation, ...] = (CardLocation.HAND,),
        ruleset: str | None = None,
    ):
        triggers.watch(
            printed_id,
            key=key,
            condition=condition,
            reaction=reaction,
            where=where,
            ruleset=ruleset,
        )
        registered.append(printed_id)

    yield _register
    for printed_id in registered:
        triggers._WATCHES.pop(printed_id, None)


@contextmanager
def probe_ability(printed_id: str, ability: Ability):
    """Register ``ability`` under ``printed_id`` for the body of a ``with`` and remove it after.

    The ability registry is module-global, so a probe left behind is offered in every later test
    in the process.
    """
    register_ability(printed_id, ability)
    try:
        yield
    finally:
        _ABILITIES.pop(printed_id)
