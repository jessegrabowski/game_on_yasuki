from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.economy import active_modifiers, effective_gold_production

from tests.yasuki_core.engine.builders import holding, put_in_play, two_seat_game
from yasuki_core.game_pieces.cards import L5RCard


def _game(card: L5RCard, modifiers=()) -> GameState:
    game = two_seat_game()
    put_in_play(game, card)
    game.modifiers.extend(modifiers)
    return game


def test_a_wealth_counter_yields_a_derived_while_source_modifier():
    farm = holding("f", gold_production=2, counters={"wealth": 2})
    game = _game(farm)
    mods = list(active_modifiers(game, farm, Stat.GOLD_PRODUCTION))

    assert [m.amount for m in mods] == [2]  # +1GP per wealth token, aggregated
    assert mods[0].duration is Duration.WHILE_SOURCE_IN_PLAY and mods[0].source_id == "f"


def test_effective_gp_sums_base_counters_and_recorded_modifiers():
    farm = holding("f", gold_production=2, counters={"wealth": 1})
    recorded = Modifier("src", "f", Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    game = _game(farm, [recorded])

    assert effective_gold_production(game, farm) == 2 + 1 + 2  # base + wealth + recorded grant


def test_effective_gp_floors_at_zero():
    farm = holding("f", gold_production=2)
    penalty = Modifier("src", "f", Stat.GOLD_PRODUCTION, -5, Duration.UNTIL_END_OF_TURN)
    game = _game(farm, [penalty])

    assert effective_gold_production(game, farm) == 0  # 2 - 5, floored


def test_while_source_in_play_modifier_is_ignored_when_its_source_is_absent():
    farm = holding("f", gold_production=2)
    # "ghost" is not on the battlefield; a PERMANENT one from the same absent source still applies.
    game = _game(
        farm,
        [
            Modifier("ghost", "f", Stat.GOLD_PRODUCTION, 3, Duration.WHILE_SOURCE_IN_PLAY),
            Modifier("ghost", "f", Stat.GOLD_PRODUCTION, 4, Duration.PERMANENT),
        ],
    )

    assert effective_gold_production(game, farm) == 2 + 4  # the WHILE_SOURCE one drops out
