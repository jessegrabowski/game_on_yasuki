from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import (
    _ABILITIES,
    _INVEST,
    ENTRY_STATES,
    GRANTED_ABILITIES,
    EntryState,
    abilities_for,
    ability_for,
    ability_registrations,
    entry_state,
    entry_state_of,
    granted_ability,
    register_ability,
    register_invest,
)

# Without this the registries are empty and a lookup for a real card raises instead of testing.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.game_pieces.factory import resolve_decklist
from yasuki_core.engine.rules.vocabulary.modifiers import AbilityGrant, Duration
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint, StrongholdPrint
from tests.yasuki_core.engine.builders import holding, personality, put_in_play, two_seat_game

SHE = ruleset.SHATTERED_EMPIRE.name
IMPERIAL = ruleset.IMPERIAL.name


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


def test_a_flipped_card_dispatches_to_its_back_faces_ability():
    plain = _ABILITIES["millet_farm"][0]
    register_ability("flip_probe__back", replace(plain, label="Open: Flipped"))

    try:
        card = L5RCard.of(
            StrongholdPrint,
            id="probe",
            name="Probe",
            printed_id="flip_probe",
            side=Side.STRONGHOLD,
            back_card_id="flip_probe__back",
            back_printed=StrongholdPrint(
                name="Probe", side=Side.STRONGHOLD, printed_id="flip_probe__back"
            ),
            owner=PlayerId.P1,
        )
        game = two_seat_game()
        assert ability_for(game, card) is None

        card.flip_face()

        assert ability_for(game, card).label == "Open: Flipped"
    finally:
        _ABILITIES.pop("flip_probe__back", None)


@pytest.mark.xfail(
    strict=True,
    reason="the deck query excludes back rows, so the factory synthesizes a back that keeps the "
    "front's printed_id; real back records are the next step of the active-face plan",
)
def test_a_factory_built_card_flipped_dispatches_to_its_back():
    plain = _ABILITIES["millet_farm"][0]
    register_ability("kyuden_probe__back", replace(plain, label="Open: Flipped"))
    record = {
        "card_id": "kyuden_probe",
        "name": "Kyuden Probe",
        "extended_title": "Kyuden Probe",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
        "back_card_id": "kyuden_probe__back",
        "prints": [
            {"print_id": 1, "set_name": "S", "image_path": "a.png", "back_image_path": "b.png"}
        ],
    }

    try:
        deck = parse_deck_yaml("name: T\nPre-Game:\n  - Kyuden Probe")
        card = resolve_decklist(deck, [record], PlayerId.P1).pre_game[0]
        card.flip_face()

        assert ability_for(two_seat_game(), card).label == "Open: Flipped"
    finally:
        _ABILITIES.pop("kyuden_probe__back", None)


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


def test_a_second_entry_state_for_one_card_is_refused():
    entry_state("guard_probe")(lambda game, card: EntryState())

    try:
        with pytest.raises(ValueError, match="guard_probe already names the state"):
            entry_state("guard_probe")(lambda game, card: EntryState())
    finally:
        ENTRY_STATES.pop("guard_probe")


def test_the_rulebook_bows_an_entering_holding_and_leaves_a_personality_as_he_stands():
    game = two_seat_game()

    assert entry_state_of(game, holding("farm")) == EntryState(bowed=True, dishonorable=None)
    assert entry_state_of(game, personality("samurai")) == EntryState(
        bowed=False, dishonorable=None
    )


def test_a_cards_entry_state_overrides_only_the_fields_it_sets():
    game = two_seat_game()
    entry_state("guard_probe")(lambda game, card: EntryState(dishonorable=True))

    try:
        state = entry_state_of(game, personality("samurai", printed_id="guard_probe"))
    finally:
        ENTRY_STATES.pop("guard_probe")

    assert state == EntryState(bowed=False, dishonorable=True)


def _probe_card(printed_id: str) -> L5RCard:
    return L5RCard.of(
        HoldingPrint,
        id="probe",
        name="Probe",
        printed_id=printed_id,
        side=Side.DYNASTY,
        owner=PlayerId.P1,
    )


def test_an_ability_naming_a_ruleset_is_read_only_while_it_is_active(monkeypatch):
    plain = _ABILITIES["millet_farm"][0]
    register_ability("scope_probe", replace(plain, label="ShE", ruleset=SHE))
    register_ability("scope_probe", replace(plain, label="Imperial", ruleset=IMPERIAL))

    try:
        game = two_seat_game()
        card = _probe_card("scope_probe")
        assert [held.label for held in abilities_for(game, card)] == ["ShE"]

        monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)
        assert [held.label for held in abilities_for(game, card)] == ["Imperial"]
    finally:
        _ABILITIES.pop("scope_probe")


def test_an_ability_naming_no_ruleset_is_read_under_every_one(monkeypatch):
    plain = _ABILITIES["millet_farm"][0]
    register_ability("scope_probe", plain)

    try:
        game = two_seat_game()
        card = _probe_card("scope_probe")
        assert abilities_for(game, card) == (plain,)

        monkeypatch.setattr(ruleset, "ACTIVE", ruleset.IMPERIAL)
        assert abilities_for(game, card) == (plain,)
    finally:
        _ABILITIES.pop("scope_probe")


def test_an_unkeyed_ability_collides_only_with_one_read_under_the_same_ruleset():
    plain = _ABILITIES["millet_farm"][0]
    register_ability("scope_probe", replace(plain, ruleset=SHE))

    try:
        register_ability("scope_probe", replace(plain, ruleset=IMPERIAL))
        with pytest.raises(ValueError, match="scope_probe prints several abilities"):
            register_ability("scope_probe", replace(plain, ruleset=SHE))
        with pytest.raises(ValueError, match="scope_probe prints several abilities"):
            register_ability("scope_probe", plain)
    finally:
        _ABILITIES.pop("scope_probe")


def test_ability_registrations_lists_what_is_in_force_under_one_ruleset():
    plain = _ABILITIES["millet_farm"][0]
    register_ability("scope_probe", replace(plain, ruleset=IMPERIAL))

    try:
        assert "scope_probe" not in ability_registrations()
        assert ability_registrations(ruleset_name=IMPERIAL)["scope_probe"] == (
            replace(plain, ruleset=IMPERIAL),
        )
    finally:
        _ABILITIES.pop("scope_probe")
