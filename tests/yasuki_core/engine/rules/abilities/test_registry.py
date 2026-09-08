from dataclasses import replace

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import BOW_WAIVERS, register_bow_waiver
from yasuki_core.engine.rules.abilities.registry import (
    _ABILITIES,
    _ENTERS_UNBOWED,
    _INVEST,
    MAY_REMAIN_BOWED,
    abilities_for,
    ability_for,
    register_may_remain_bowed,
    register_ability,
    register_enters_unbowed,
    register_invest,
)
from yasuki_core.engine.rules.rulebook.lobby import MAY_NOT_LOBBY, register_may_not_lobby

# Without this the registries are empty and a lookup for a real card raises instead of testing.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint


def test_a_second_unkeyed_ability_for_one_card_is_refused():
    """An unkeyed ability is "the card's only one", so a second cannot also be unkeyed — an action
    naming neither would have no way to say which it takes."""
    # These three registries were dict literals until the card modules split them up, where a
    # repeated key was ruff's F601 to catch. Registration-time checks replace that guard.
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", plain)

    try:
        with pytest.raises(ValueError, match="guard_probe prints several abilities"):
            register_ability("guard_probe", plain)
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_second_ability_may_not_repeat_a_key():
    """Keys are how an action names an ability, so two abilities answering to the same one would
    make the choice unresolvable."""
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", replace(plain, key="first"))

    try:
        with pytest.raises(ValueError, match="already has an ability keyed 'first'"):
            register_ability("guard_probe", replace(plain, key="first"))
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_card_may_register_several_keyed_abilities():
    """The point of the key: two abilities under one printed id, each retrievable by name."""
    plain = _ABILITIES["millet_farm"][0]
    register_ability("guard_probe", replace(plain, key="fear", label="Battle: Fear 3"))
    register_ability("guard_probe", replace(plain, key="ranged", label="Battle: Ranged 3"))

    try:
        card = L5RCard.of(
            HoldingPrint,
            id="probe",
            name="Probe",
            printed_id="guard_probe",
            side=Side.DYNASTY,
            owner=PlayerId.P1,
        )
        assert [held.key for held in abilities_for(card)] == ["fear", "ranged"]
        assert ability_for(card, "ranged").label == "Battle: Ranged 3"
        assert ability_for(card, "absent") is None
        with pytest.raises(ValueError, match="prints several abilities; name one by key"):
            ability_for(card)
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_second_invest_for_one_card_is_refused():
    register_invest("guard_probe", _INVEST["training_court"])

    try:
        with pytest.raises(ValueError, match="guard_probe already has an invest ability"):
            register_invest("guard_probe", _INVEST["training_court"])
    finally:
        _INVEST.pop("guard_probe", None)


def test_a_second_enters_unbowed_for_one_card_is_refused():
    # A set absorbs a repeated registration where the dict registries raise, so without this guard a
    # card listed from two set modules would be invisible rather than loud.
    register_enters_unbowed("guard_probe")

    try:
        with pytest.raises(ValueError, match="guard_probe already enters play unbowed"):
            register_enters_unbowed("guard_probe")
    finally:
        _ENTERS_UNBOWED.discard("guard_probe")


@pytest.mark.parametrize(
    "register_flag, registry, complaint",
    [
        (register_bow_waiver, BOW_WAIVERS, "already waives a bow cost"),
        (register_may_not_lobby, MAY_NOT_LOBBY, "already may not be bowed to Lobby"),
        (register_may_remain_bowed, MAY_REMAIN_BOWED, "may already remain bowed"),
    ],
    ids=["register_bow_waiver", "register_may_not_lobby", "register_may_remain_bowed"],
)
def test_a_second_flag_registration_for_one_card_is_refused(register_flag, registry, complaint):
    # A flat set absorbs a repeated registration, so without this guard a card listed from two set
    # modules is invisible rather than loud — the same failure register_enters_unbowed guards above.
    register_flag("guard_probe")

    try:
        with pytest.raises(ValueError, match=f"guard_probe {complaint}"):
            register_flag("guard_probe")
    finally:
        registry.discard("guard_probe")
