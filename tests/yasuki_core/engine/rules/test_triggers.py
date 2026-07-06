from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.effects import effective_gold_production
from yasuki_core.engine.rules.events import CardDiscarded, TurnStarted
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
from yasuki_core.game_pieces.fate import FateCard


def _game():
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1)


def _rice_farm(game, seat=PlayerId.P1, card_id="P1-farm"):
    # Rice Farm's printed Gold Production is 0; its output is entirely the Wealth tokens it accrues.
    farm = DynastyHolding(
        id=card_id,
        printed_id="rice_farm",
        name="Rice Farm",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=0,
    )
    game.table.cards_by_id[farm.id] = farm
    game.table.battlefield.add(farm)
    return farm


def test_turn_start_gives_the_rice_farm_a_wealth_token():
    game = _game()
    farm = _rice_farm(game)

    fire(game, TurnStarted(PlayerId.P1))

    assert farm.counters == {"wealth": 1}


def test_wealth_accrues_each_turn_up_to_the_cap_of_four():
    game = _game()
    farm = _rice_farm(game)

    for _ in range(6):
        fire(game, TurnStarted(PlayerId.P1))

    assert farm.counters == {"wealth": 4}  # "will not have more than four Wealth tokens"


def test_one_event_fans_out_to_every_subscribed_card():
    game = _game()
    first = _rice_farm(game, card_id="P1-farm-a")
    second = _rice_farm(game, card_id="P1-farm-b")

    fire(game, TurnStarted(PlayerId.P1))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}


def test_the_token_only_lands_on_the_turn_players_own_farm():
    game = _game()
    farm = _rice_farm(game)  # owned by P1

    fire(game, TurnStarted(PlayerId.P2))  # "after your turn begins" — not P1's turn

    assert farm.counters == {}


def test_accrued_wealth_raises_the_farms_effective_gold_production():
    game = _game()
    farm = _rice_farm(game)
    assert effective_gold_production(game, farm) == 0

    fire(game, TurnStarted(PlayerId.P1))
    fire(game, TurnStarted(PlayerId.P1))

    assert effective_gold_production(game, farm) == 2  # printed 0 + two Wealth tokens


def test_flow_emits_the_turn_start_event_from_begin_turn():
    # The wiring test: begin_game runs _begin_turn, which must fire TurnStarted.
    game = _game()
    farm = _rice_farm(game)

    flow.begin_game(game)

    assert farm.counters == {"wealth": 1}


def _caravansary(game, seat=PlayerId.P1, card_id="P1-caravansary"):
    holding = DynastyHolding(
        id=card_id,
        printed_id="caravansary",
        name="Caravansary",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=2,
    )
    game.table.cards_by_id[holding.id] = holding
    game.table.battlefield.add(holding)
    return holding


def test_caravansary_gains_wealth_when_you_discard_a_fate_card():
    game = _game()
    caravansary = _caravansary(game)

    fire(game, CardDiscarded("some-fate", Side.FATE, PlayerId.P1))

    assert caravansary.counters == {"wealth": 1}


def test_caravansary_ignores_an_opponents_discard():
    game = _game()
    caravansary = _caravansary(game)  # owned by P1

    fire(game, CardDiscarded("some-fate", Side.FATE, PlayerId.P2))  # not your action

    assert caravansary.counters == {}


def test_caravansary_ignores_a_dynasty_discard():
    game = _game()
    caravansary = _caravansary(game)

    fire(game, CardDiscarded("some-dynasty", Side.DYNASTY, PlayerId.P1))  # not a Fate card

    assert caravansary.counters == {}


def test_caravansary_wealth_caps_at_three():
    game = _game()
    caravansary = _caravansary(game)

    for _ in range(5):
        fire(game, CardDiscarded("some-fate", Side.FATE, PlayerId.P1))

    assert caravansary.counters == {"wealth": 3}


def test_flow_emits_the_discard_event_from_the_end_of_turn_discard():
    # The wiring test: _apply_discard moves a hand card to the discard and must fire CardDiscarded.
    game = _game()
    caravansary = _caravansary(game)
    fate = FateCard(id="P1-f", name="F", side=Side.FATE, owner=PlayerId.P1)
    game.table.cards_by_id[fate.id] = fate
    game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(fate)

    flow._apply_discard(game, PlayerId.P1, ("P1-f",))

    assert caravansary.counters == {"wealth": 1}
