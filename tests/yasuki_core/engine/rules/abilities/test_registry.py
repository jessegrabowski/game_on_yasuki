from dataclasses import replace

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import (
    _ABILITIES,
    _ENTERS_UNBOWED,
    _INVEST,
    GRANTED_ABILITIES,
    abilities_for,
    ability_for,
    granted_ability,
    register_ability,
    register_enters_unbowed,
    register_invest,
)

# Without this the registries are empty and a lookup for a real card raises instead of testing.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.engine.rules.vocabulary.modifiers import AbilityGrant, Duration
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game


def test_a_second_unkeyed_ability_for_one_card_is_refused():
    """An unkeyed ability is "the card's only one", so a second cannot also be unkeyed, since an
    action naming neither would have no way to say which it takes."""
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
        game = two_seat_game()
        assert [held.key for held in abilities_for(game, card)] == ["fear", "ranged"]
        assert ability_for(game, card, "ranged").label == "Battle: Ranged 3"
        assert ability_for(game, card, "absent") is None
        with pytest.raises(ValueError, match="prints several abilities; name one by key"):
            ability_for(game, card)
    finally:
        _ABILITIES.pop("guard_probe", None)


def test_a_granted_ability_follows_the_printed_ones_and_answers_to_its_key():
    plain = _ABILITIES["millet_farm"][0]
    granted_ability("grant_probe")(
        lambda context: replace(plain, key=f"granted_{context[0]}", label="Battle: Ranged 3")
    )

    try:
        game = two_seat_game()
        granting = put_in_play(game, holding("granting", printed_id="grant_probe"))
        farm = put_in_play(game, holding("farm", printed_id="millet_farm"))
        game.ongoing.append(
            AbilityGrant(granting.id, farm.id, ("raider",), Duration.WHILE_SOURCE_IN_PLAY)
        )

        assert [held.key for held in abilities_for(game, farm)] == [None, "granted_raider"]
        assert ability_for(game, farm, "granted_raider").label == "Battle: Ranged 3"

        game.table.battlefield.remove(granting)

        assert abilities_for(game, farm) == (plain,)
    finally:
        GRANTED_ABILITIES.pop("grant_probe", None)


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
