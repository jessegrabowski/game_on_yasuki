from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import enforce_state_rules, resolve_effects
from yasuki_core.engine.table import BATTLEFIELD
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.rules.economy import (
    active_modifiers,
    effective_gold_cost,
    effective_gold_production,
)

from tests.yasuki_core.engine.builders import (
    holding,
    personality,
    province_card,
    put_in_play,
    two_seat_game,
)
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


def test_effective_gold_cost_sums_the_printed_cost_and_recorded_modifiers():
    mine = holding("m", gold_cost=3)
    rider = Modifier("src", "m", Stat.GOLD_COST, 1, Duration.PERMANENT)
    game = _game(mine, [rider])

    assert effective_gold_cost(game, mine) == 4


def test_effective_gold_cost_floors_at_zero():
    mine = holding("m", gold_cost=2)
    discount = Modifier("src", "m", Stat.GOLD_COST, -5, Duration.UNTIL_END_OF_TURN)
    game = _game(mine, [discount])

    assert effective_gold_cost(game, mine) == 0


def test_a_card_printing_no_gold_cost_is_free_and_takes_no_modifier():
    """A dash Gold Cost is an absent stat, and an absent stat has nothing to modify."""
    mine = holding("m")
    rider = Modifier("src", "m", Stat.GOLD_COST, 3, Duration.PERMANENT)
    game = _game(mine, [rider])

    assert mine.gold_cost is None
    assert effective_gold_cost(game, mine) == 0


def test_a_permanent_modifier_is_forgotten_when_its_target_leaves_play():
    """A card that leaves play ceases to exist (CR), so nothing granted to it survives. PERMANENT
    outlives its *source* going away, which is a different thing."""
    mine = holding("m", gold_cost=3)
    game = _game(mine, [Modifier("src", "m", Stat.GOLD_COST, 1, Duration.PERMANENT)])
    assert effective_gold_cost(game, mine) == 4

    resolve_effects(game, [Destroy("m", PlayerId.P1)])

    assert effective_gold_cost(game, mine) == 3
    assert game.modifiers == []  # forgotten, not merely skipped while it is away


def test_a_card_waiting_in_a_province_keeps_its_modifiers():
    """A Province card has not left play — it has not entered yet. Repairing the Ruins raises a
    Holding's Gold Cost while it waits in one, so sweeping it off the table would erase the card."""
    game = two_seat_game()
    waiting = province_card(game.table, "m", printed_id="m", gold_cost=3, index=0)
    game.modifiers.append(Modifier("src", "m", Stat.GOLD_COST, 1, Duration.PERMANENT))

    enforce_state_rules(game)

    assert effective_gold_cost(game, waiting) == 4


def test_a_province_cards_modifier_survives_the_move_into_play():
    """The raised cost is what the seat pays to Recruit it, so it has to cross province to play."""
    game = two_seat_game()
    waiting = province_card(game.table, "m", printed_id="m", gold_cost=3, index=0)
    game.modifiers.append(Modifier("src", "m", Stat.GOLD_COST, 1, Duration.PERMANENT))
    enforce_state_rules(game)

    ops.move_card(game.table, waiting, BATTLEFIELD)
    enforce_state_rules(game)

    assert effective_gold_cost(game, waiting) == 4


def test_a_card_a_state_rule_destroys_loses_its_modifiers_in_the_same_enforcement():
    """The sweep and the state rules share a fixpoint, so a Personality killed by the Chi Death Rule
    has his modifiers gone before enforcement returns rather than at whatever happens next."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, chi=1))
    game.modifiers.extend(
        [
            Modifier("src", hero.id, Stat.CHI, -1, Duration.PERMANENT),
            Modifier("src", hero.id, Stat.FORCE, 3, Duration.PERMANENT),
        ]
    )

    enforce_state_rules(game)

    assert hero not in game.table.battlefield.cards
    assert game.modifiers == []
