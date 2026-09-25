import pytest

from yasuki_core.engine.players import PlayerId, Rulebook, Trait
from yasuki_core.engine.rules.battle import resolution
from yasuki_core.engine.rules.battle.presence import place_unit
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import Location, location_of

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    province_card,
    put_in_play,
    terrain_at,
    two_seat_game,
)


def _declared_game():
    game = two_seat_game()
    province_card(game, "def-prov0", seat=PlayerId.P2, index=0)
    put_in_play(game, personality("hero"))
    attached(game, attachment("blade"), "hero")
    resolution.declare_attack(game)
    return game


def test_placing_an_attached_card_records_its_personality():
    game = _declared_game()

    place_unit(game, game.table.cards_by_id["blade"], Location.at_battlefield(0))

    assert game.attack.battlefields[0].ever_present == frozenset({(PlayerId.P1, "hero")})
    assert location_of(game.table, game.table.cards_by_id["hero"]).battlefield == 0


def test_sending_a_unit_home_leaves_the_record_as_it_was():
    game = _declared_game()
    hero = game.table.cards_by_id["hero"]
    place_unit(game, hero, Location.at_battlefield(0))

    place_unit(game, hero, Location.home(PlayerId.P1))

    assert game.attack.battlefields[0].ever_present == frozenset({(PlayerId.P1, "hero")})
    assert location_of(game.table, hero).is_home


def test_a_move_outside_an_attack_records_nothing():
    game = two_seat_game()
    put_in_play(game, personality("hero"))

    assert place_unit(game, game.table.cards_by_id["hero"], Location.home(PlayerId.P1)) is False
    assert game.attack is None


@pytest.mark.parametrize(
    ("cause", "recorded"),
    [
        (PlayerId.P2, frozenset({(PlayerId.P2, "ground")})),
        (Trait("shaman"), frozenset({(PlayerId.P2, "ground")})),
        (Trait("departed"), frozenset()),
        (Rulebook.BATTLE_RESOLUTION, frozenset()),
    ],
    ids=["seat", "trait", "trait-of-a-departed-card", "rulebook"],
)
def test_destroying_a_terrain_at_a_battlefield_records_the_seat_it_belongs_to(cause, recorded):
    game = _declared_game()
    put_in_play(game, personality("shaman", owner=PlayerId.P2))
    terrain_at(game, "ground", battlefield=0, owner=PlayerId.P1)

    resolve_effects(game, [Destroy("ground", cause)])

    assert game.attack.battlefields[0].terrains_destroyed == recorded


def test_destroying_a_card_at_a_battlefield_that_is_no_terrain_records_nothing():
    game = _declared_game()
    hero = game.table.cards_by_id["hero"]
    place_unit(game, hero, Location.at_battlefield(0))

    resolve_effects(game, [Destroy("hero", PlayerId.P2)])

    assert game.attack.battlefields[0].terrains_destroyed == frozenset()
