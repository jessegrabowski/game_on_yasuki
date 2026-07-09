from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import flow
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.rules.effects import effective_gold_production
from yasuki_core.engine.rules.events import CardDiscarded, Destroyed, EnteredPlay, TurnStarted
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import AdjustCounter, Destroy, apply_effect, fire, on
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.fate import FateCard


# A test-only trigger: any card printed as "test_probe" gives itself a Wealth token when a card
# enters play. It lets a co-firing subscriber do observable work, which no real EnteredPlay card
# pairs with Wheat Farm to do.
@on(EnteredPlay, "test_probe")
def _probe_gains_wealth(ctx):
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]


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


def _aoki(game, seat=PlayerId.P1, card_id="P1-aoki"):
    aoki = DynastyPersonality(
        id=card_id,
        printed_id="shosuro_aoki_yoritomo_kayoko_experienced",
        name="Shosuro Aoki",
        side=Side.DYNASTY,
        owner=seat,
    )
    game.table.cards_by_id[aoki.id] = aoki
    game.table.battlefield.add(aoki)
    return aoki


def _seed_fate_deck(game, seat, count):
    deck = game.table.decks[DeckKey(seat, Side.FATE)]
    deck.cards = [
        FateCard(id=f"{seat.name}-fd{i}", name="F", side=Side.FATE, owner=seat)
        for i in range(count)
    ]
    for card in deck.cards:
        game.table.cards_by_id[card.id] = card


def _hand_size(game, seat):
    return len(game.table.zones[ZoneKey(seat, ZoneRole.HAND)].cards)


def test_gaining_wealth_cascades_into_aokis_draw():
    # The cascade: turn start -> Rice Farm gains wealth -> CounterGained -> Aoki draws a card.
    game = _game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)
    assert _hand_size(game, PlayerId.P1) == 0

    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 1


def test_aoki_draws_at_most_once_per_turn():
    game = _game()
    _rice_farm(game, card_id="P1-farm-a")
    _rice_farm(game, card_id="P1-farm-b")  # two wealth gains in one turn
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 1  # two CounterGained events, one draw


def test_aoki_draws_again_on_the_next_turn():
    # The once-per-turn claim is turn-scoped: a fresh turn re-arms Aoki's draw.
    game = _game()
    _rice_farm(game)
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P1))
    game.turn += 1
    fire(game, TurnStarted(PlayerId.P1))

    assert _hand_size(game, PlayerId.P1) == 2


def test_aoki_ignores_wealth_gained_on_an_opponents_holding():
    game = _game()
    _aoki(game, seat=PlayerId.P1)
    _rice_farm(game, seat=PlayerId.P2, card_id="P2-farm")
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, TurnStarted(PlayerId.P2))  # P2's farm gains wealth — not Aoki's Holding

    assert _hand_size(game, PlayerId.P1) == 0


def _rural_market(game, seat=PlayerId.P1, card_id="P1-rural"):
    holding = DynastyHolding(
        id=card_id,
        printed_id="rural_market",
        name="Rural Market",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=0,
    )
    game.table.cards_by_id[holding.id] = holding
    game.table.battlefield.add(holding)
    return holding


def _keyworded_farm(game, seat=PlayerId.P1, card_id="P1-a-farm"):
    farm = DynastyHolding(
        id=card_id,
        printed_id="a_farm",
        name="A Farm",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=1,
        keywords=("Farm",),
    )
    game.table.cards_by_id[farm.id] = farm
    game.table.battlefield.add(farm)
    return farm


def test_destroy_effect_discards_the_card_and_emits_destroyed():
    game = _game()
    farm = _keyworded_farm(game)

    events = apply_effect(game, Destroy(farm.id))

    assert events == [Destroyed(farm.id)]
    assert farm not in game.table.battlefield.cards
    assert farm in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards


def test_destroy_routes_a_fate_card_to_the_fate_discard():
    game = _game()
    follower = FateCard(id="P1-follower", name="F", side=Side.FATE, owner=PlayerId.P1)
    game.table.cards_by_id[follower.id] = follower
    game.table.battlefield.add(follower)

    apply_effect(game, Destroy(follower.id))

    assert follower in game.table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards


def test_destroying_your_farm_gives_rural_market_a_wealth_token():
    game = _game()
    rural = _rural_market(game)
    farm = _keyworded_farm(game)

    fire(game, Destroyed(farm.id))

    assert rural.counters == {"wealth": 1}


def test_rural_market_ignores_a_non_farm_destruction():
    game = _game()
    rural = _rural_market(game)
    holding = _caravansary(game)  # a Holding, but not a Farm

    fire(game, Destroyed(holding.id))

    assert rural.counters == {}


def test_rural_market_ignores_an_opponents_farm():
    game = _game()
    rural = _rural_market(game, seat=PlayerId.P1)
    farm = _keyworded_farm(game, seat=PlayerId.P2, card_id="P2-a-farm")

    fire(game, Destroyed(farm.id))

    assert rural.counters == {}


def test_rural_market_gains_wealth_when_it_enters_play():
    game = _game()
    rural = _rural_market(game)

    fire(game, EnteredPlay(rural.id))

    assert rural.counters == {"wealth": 1}


def test_rural_market_ignores_another_cards_entry():
    game = _game()
    rural = _rural_market(game)
    other = _keyworded_farm(game)  # some other Holding entering play

    fire(game, EnteredPlay(other.id))

    assert rural.counters == {}  # "after THIS Holding enters play" — only its own entry


def test_flow_emits_entered_play_from_recruit_resolution():
    # The wiring test: _resolve_recruit moves the card into play and must fire EnteredPlay.
    game = _game()
    rural = DynastyHolding(
        id="P1-rural",
        printed_id="rural_market",
        name="Rural Market",
        side=Side.DYNASTY,
        owner=PlayerId.P1,
        gold_production=0,
    )
    game.table.cards_by_id[rural.id] = rural  # being recruited, not yet on the battlefield

    flow._resolve_recruit(game, PlayerId.P1, rural.id)

    assert rural in game.table.battlefield.cards
    assert rural.counters == {"wealth": 1}


def _wheat_farm(game, seat=PlayerId.P1, card_id="P1-wheat"):
    farm = DynastyHolding(
        id=card_id,
        printed_id="wheat_farm",
        name="Wheat Farm",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=2,
        keywords=("Farm",),
    )
    game.table.cards_by_id[farm.id] = farm
    game.table.battlefield.add(farm)
    return farm


def test_wheat_farm_offers_no_choice_without_other_farms():
    game = _game()
    wheat = _wheat_farm(game)

    fire(game, EnteredPlay(wheat.id))

    assert game.pending is None
    assert wheat.counters == {}  # it seeds no token on itself


def test_wheat_farm_pauses_to_choose_among_your_other_farms():
    game = _game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))

    pending = game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.seat is PlayerId.P1
    assert pending.candidates == (other.id,)  # excludes the Wheat Farm itself
    assert (pending.minimum, pending.maximum) == (0, 1)  # zero to two, capped by the one candidate


def test_wheat_farm_excludes_non_farms_and_opponents_farms():
    game = _game()
    wheat = _wheat_farm(game)
    _caravansary(game)  # a Holding, but not a Farm
    _keyworded_farm(game, seat=PlayerId.P2, card_id="P2-farm")  # a Farm, but the opponent's

    fire(game, EnteredPlay(wheat.id))

    assert game.pending is None  # no eligible target — no choice raised


def test_wheat_farm_grants_a_token_to_each_chosen_farm():
    game = _game()
    wheat = _wheat_farm(game)
    first = _keyworded_farm(game, card_id="P1-farm-a")
    second = _keyworded_farm(game, card_id="P1-farm-b")

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse((first.id, second.id)))

    assert first.counters == {"wealth": 1} and second.counters == {"wealth": 1}
    assert wheat.counters == {}
    assert game.pending is None


def test_wheat_farm_choice_is_optional():
    game = _game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse(()))  # decline — give none

    assert other.counters == {}
    assert game.pending is None


def test_wheat_farm_token_cascades_into_aokis_draw():
    game = _game()
    wheat = _wheat_farm(game)
    other = _keyworded_farm(game, card_id="P1-other-farm")
    _aoki(game)
    _seed_fate_deck(game, PlayerId.P1, 3)

    fire(game, EnteredPlay(wheat.id))
    flow.submit(game, DecisionResponse((other.id,)))

    assert _hand_size(game, PlayerId.P1) == 1  # the granted token drew Aoki a card


def test_wheat_farm_caps_the_choice_at_two_farms():
    game = _game()
    wheat = _wheat_farm(game)
    for i in range(3):
        _keyworded_farm(game, card_id=f"P1-farm-{i}")

    fire(game, EnteredPlay(wheat.id))

    pending = game.pending
    assert isinstance(pending, ChooseCards)
    assert len(pending.candidates) == 3
    assert pending.maximum == 2  # "zero to two" — capped however many Farms you control


def _probe(game, seat=PlayerId.P1, card_id="P1-z-probe"):
    probe = DynastyHolding(
        id=card_id, printed_id="test_probe", name="Probe", side=Side.DYNASTY, owner=seat
    )
    game.table.cards_by_id[probe.id] = probe
    game.table.battlefield.add(probe)
    return probe


def test_a_trigger_stashed_by_the_choice_still_applies_its_effect_on_resume():
    # The probe also fires on the Wheat Farm's entry but sorts after it, so the pausing choice stashes
    # the probe's trigger; resuming must run it and land its Wealth token, not merely drain the stack.
    game = _game()
    wheat = _wheat_farm(game, card_id="P1-a-wheat")
    other = _keyworded_farm(game, card_id="P1-other-farm")
    probe = _probe(game)

    fire(game, EnteredPlay(wheat.id))
    assert isinstance(game.pending, ChooseCards)  # paused with the probe's trigger stashed
    flow.submit(game, DecisionResponse((other.id,)))

    assert other.counters == {"wealth": 1}  # the choice resolved
    assert probe.counters == {"wealth": 1}  # the stashed trigger resumed and applied its effect
    assert game.stack == []
