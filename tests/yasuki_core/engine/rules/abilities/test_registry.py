from dataclasses import replace

import pytest

from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.registry import (
    ability_label,
    _ABILITIES,
    _INVEST,
    ENTRY_STATES,
    GRANTED_ABILITIES,
    KEYWORD_ABILITIES,
    LOCATION_ABILITIES,
    EntryState,
    abilities_for,
    ability_for,
    ability_registrations,
    entry_state,
    entry_state_of,
    granted_ability,
    register_ability,
    register_invest,
    register_keyword_ability,
    register_location_ability,
)

# Without this the registries are empty and a lookup for a real card raises instead of testing.
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.game_pieces.factory import resolve_decklist
from yasuki_core.engine.rules.vocabulary.modifiers import (
    AbilityGrant,
    Duration,
    KeywordGrant,
    SeatAbilityGrant,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import HoldingPrint, StrongholdPrint
from tests.yasuki_core.engine.builders import (
    fate_card,
    holding,
    personality,
    put_in_play,
    register,
    two_seat_game,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole

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


def test_a_factory_built_card_flipped_dispatches_to_its_back():
    plain = _ABILITIES["millet_farm"][0]
    register_ability("kyuden_probe__back", replace(plain, label="Open: Flipped"))
    front = {
        "card_id": "kyuden_probe",
        "name": "Kyuden Probe",
        "extended_title": "Kyuden Probe",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
        "back_card_id": "kyuden_probe__back",
        "prints": [{"print_id": 1, "set_name": "S", "image_path": "a.png"}],
    }
    back = {
        "card_id": "kyuden_probe__back",
        "name": "Kyuden Probe",
        "extended_title": "Kyuden Probe",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
        "prints": [{"print_id": 2, "set_name": "S", "image_path": "b.png"}],
    }

    try:
        deck = parse_deck_yaml("name: T\nPre-Game:\n  - Kyuden Probe")
        card = resolve_decklist(deck, [front], PlayerId.P1, backs=[back]).pre_game[0]
        card.flip_face()

        assert ability_for(two_seat_game(), card).label == "Open: Flipped"
    finally:
        _ABILITIES.pop("kyuden_probe__back", None)


def test_a_granted_ability_follows_the_printed_ones_and_answers_to_its_key():
    plain = _ABILITIES["millet_farm"][0]
    granted_ability("grant_probe")(
        lambda game, card, context: replace(
            plain, key=f"granted_{context[0]}", label="Battle: Ranged 3"
        )
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


def _labelless(**fields) -> Ability:
    return Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=lambda game, source: [],
        effects=lambda game, source, target: [],
        **fields,
    )


def _printed(text: str) -> L5RCard:
    return L5RCard.of(
        HoldingPrint, id="farm", name="Farm", side=Side.DYNASTY, owner=PlayerId.P1, text=text
    )


def test_an_unlabeled_ability_shows_the_printed_line_its_index_names():
    card = _printed(
        "<b>Open, :bow::</b> Give your target Farm Holding +2GP.<br><b>Open:</b> Draw a card."
    )

    assert ability_label(card, _labelless()) == "Open, :bow:: Give your target Farm Holding +2GP."
    assert ability_label(card, _labelless(printed_index=1)) == "Open: Draw a card."


def test_a_labeled_ability_shows_its_label_whatever_the_card_prints():
    card = _printed("<b>Open:</b> Draw a card.")

    assert ability_label(card, _labelless(label="Open: Put this Event into play")) == (
        "Open: Put this Event into play"
    )


def test_a_card_built_without_its_text_shows_its_name():
    card = holding("farm", name="Rice Farm")

    assert ability_label(card, _labelless()) == "Rice Farm"


def test_a_seat_grant_reaches_every_card_its_seat_owns_and_none_of_the_opponents():
    plain = _ABILITIES["millet_farm"][0]
    granted_ability("grant_probe")(lambda game, card, context: replace(plain, key=context[0]))

    try:
        game = two_seat_game()
        granting = put_in_play(game, holding("granting", printed_id="grant_probe"))
        own = put_in_play(game, holding("own"))
        theirs = put_in_play(game, holding("theirs", owner=PlayerId.P2))
        held = fate_card("held", PlayerId.P1)
        game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(register(game.table, held))
        game.ongoing.append(
            SeatAbilityGrant(granting.id, PlayerId.P1, ("licensed",), Duration.UNTIL_END_OF_TURN)
        )

        assert [held.key for held in abilities_for(game, own)] == ["licensed"]
        assert [held.key for held in abilities_for(game, held)] == ["licensed"]
        assert abilities_for(game, theirs) == ()
    finally:
        GRANTED_ABILITIES.pop("grant_probe", None)


def test_a_keyword_ability_joins_every_card_carrying_the_keyword_after_its_own():
    plain = _ABILITIES["millet_farm"][0]
    register_keyword_ability(replace(plain, key="probe", from_keyword="Probe"))

    try:
        game = two_seat_game()
        farm = put_in_play(game, holding("farm", printed_id="millet_farm", keywords=("probe",)))
        bare = put_in_play(game, holding("bare", printed_id="millet_farm"))

        assert [held.key for held in abilities_for(game, farm)] == [None, "probe"]
        assert ability_for(game, farm) is plain
        assert ability_for(game, farm, "probe").from_keyword == "Probe"
        assert abilities_for(game, bare) == (plain,)
    finally:
        KEYWORD_ABILITIES.pop("probe", None)


def test_a_granted_keyword_brings_its_abilities_with_it():
    plain = _ABILITIES["millet_farm"][0]
    register_keyword_ability(replace(plain, key="probe", from_keyword="Probe"))

    try:
        game = two_seat_game()
        granting = put_in_play(game, holding("granting"))
        farm = put_in_play(game, holding("farm", printed_id="millet_farm"))
        game.ongoing.append(
            KeywordGrant(granting.id, farm.id, "Probe", Duration.WHILE_SOURCE_IN_PLAY)
        )

        assert [held.key for held in abilities_for(game, farm)] == [None, "probe"]

        game.table.battlefield.remove(granting)

        assert abilities_for(game, farm) == (plain,)
    finally:
        KEYWORD_ABILITIES.pop("probe", None)


def test_a_granted_ability_under_a_keyword_abilitys_key_stands_in_for_it():
    plain = _ABILITIES["millet_farm"][0]
    register_keyword_ability(replace(plain, key="probe", from_keyword="Probe"))
    granted_ability("grant_probe")(
        lambda game, card, context: replace(plain, key="probe", label=f"Granted to {card.id}")
    )

    try:
        game = two_seat_game()
        granting = put_in_play(game, holding("granting", printed_id="grant_probe"))
        farm = put_in_play(game, holding("farm", printed_id="millet_farm", keywords=("probe",)))
        game.ongoing.append(AbilityGrant(granting.id, farm.id, (), Duration.UNTIL_END_OF_TURN))

        assert [held.key for held in abilities_for(game, farm)] == [None, "probe"]
        assert ability_for(game, farm, "probe").label == "Granted to farm"
    finally:
        KEYWORD_ABILITIES.pop("probe", None)
        GRANTED_ABILITIES.pop("grant_probe", None)


def test_a_keyword_ability_must_name_its_keyword_and_a_key():
    plain = _ABILITIES["millet_farm"][0]

    with pytest.raises(ValueError, match="names the keyword"):
        register_keyword_ability(replace(plain, key="probe"))
    with pytest.raises(ValueError, match="needs a key"):
        register_keyword_ability(replace(plain, from_keyword="Probe"))
    assert "probe" not in KEYWORD_ABILITIES


def test_a_keyword_may_not_confer_two_abilities_under_one_key():
    plain = replace(_ABILITIES["millet_farm"][0], key="probe", from_keyword="Probe")
    register_keyword_ability(plain)

    try:
        with pytest.raises(ValueError, match="already confers an ability keyed 'probe'"):
            register_keyword_ability(plain)
    finally:
        KEYWORD_ABILITIES.pop("probe", None)


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


@pytest.fixture
def location_abilities():
    before = dict(LOCATION_ABILITIES)
    yield
    LOCATION_ABILITIES.clear()
    LOCATION_ABILITIES.update(before)


@pytest.mark.usefixtures("location_abilities")
def test_a_location_ability_joins_every_card_sitting_there_and_leaves_with_it():
    plain = _ABILITIES["millet_farm"][0]
    conferred = replace(plain, key="probe", located_at=(CardLocation.HAND,), from_location=True)
    register_location_ability(conferred)
    game = two_seat_game()
    held = fate_card("held", PlayerId.P1)
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(register(game.table, held))
    farm = put_in_play(game, holding("farm", printed_id="millet_farm"))

    assert abilities_for(game, held) == (conferred,)
    assert abilities_for(game, farm) == (plain,)
    assert ability_for(game, held, "probe").from_rulebook

    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].remove(held)
    game.table.battlefield.add(held)

    assert abilities_for(game, held) == ()


@pytest.mark.usefixtures("location_abilities")
def test_a_location_ability_must_be_marked_and_keyed_and_unique_where_it_sits():
    plain = replace(_ABILITIES["millet_farm"][0], located_at=(CardLocation.HAND,))

    with pytest.raises(ValueError, match="marked from_location"):
        register_location_ability(replace(plain, key="probe"))
    with pytest.raises(ValueError, match="needs a key"):
        register_location_ability(replace(plain, from_location=True))

    register_location_ability(replace(plain, key="probe", from_location=True))

    with pytest.raises(ValueError, match="hand already confers an ability keyed 'probe'"):
        register_location_ability(replace(plain, key="probe", from_location=True))
