from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import (
    GOLD_HANDLERS,
    effective_gold_production,
    gold_handler,
    opposing_states,
    player_state,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding, DynastyPersonality
from yasuki_core.game_pieces.pregame import StrongholdCard


def _game():
    return GameState.start(TableState.empty_two_seat(), PlayerId.P1)


def _put(game, card):
    game.table.cards_by_id[card.id] = card
    game.table.battlefield.add(card)
    return card


def _stronghold(seat, gold_production):
    return StrongholdCard(
        id=f"{seat.name}-SH",
        name="SH",
        side=Side.STRONGHOLD,
        owner=seat,
        gold_production=gold_production,
    )


def _holding(seat, card_id, *, keywords=(), printed_id=None, gold_production=2):
    return DynastyHolding(
        id=card_id,
        printed_id=printed_id,
        name="H",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=gold_production,
        keywords=keywords,
    )


def test_player_state_exposes_stronghold_holdings_gold_and_honor():
    game = _game()
    sh = _put(game, _stronghold(PlayerId.P1, 8))
    market = _put(game, _holding(PlayerId.P1, "P1-market", keywords=("Market",)))
    _put(game, _stronghold(PlayerId.P2, 5))  # an opponent's card must not leak into me.in_play
    game.table.seats[PlayerId.P1].honor = 12
    game.gold[PlayerId.P1] = 3

    me = player_state(game, PlayerId.P1)

    assert me.stronghold is sh
    assert me.holdings == (market,)
    assert me.gold == 3 and me.honor == 12
    assert set(me.in_play) == {sh, market}


def test_went_second_is_true_only_for_the_non_first_player():
    game = _game()  # first_player is P1
    assert player_state(game, PlayerId.P1).went_second is False
    assert player_state(game, PlayerId.P2).went_second is True


def test_controls_matches_a_keyword_and_can_exclude_a_card():
    game = _game()
    dockside = _put(game, _holding(PlayerId.P1, "P1-dockside", keywords=("Market",)))
    _put(game, _holding(PlayerId.P1, "P1-other-market", keywords=("Market",)))

    me = player_state(game, PlayerId.P1)

    assert me.controls("Market") is True
    assert me.controls("Port") is False
    # "another Market" — excluding the asking card still finds the second one.
    assert me.controls("Market", other_than=dockside) is True


def test_controls_other_than_the_only_match_is_false():
    game = _game()
    lone = _put(game, _holding(PlayerId.P1, "P1-lone", keywords=("Market",)))
    me = player_state(game, PlayerId.P1)
    assert me.controls("Market", other_than=lone) is False


def test_opposing_states_are_every_other_seat():
    game = _game()
    _put(game, _stronghold(PlayerId.P1, 8))
    opp_sh = _put(game, _stronghold(PlayerId.P2, 5))

    opponents = opposing_states(game, PlayerId.P1)

    assert [o.seat for o in opponents] == [PlayerId.P2]
    assert opponents[0].stronghold is opp_sh


def test_effective_gold_production_falls_back_to_printed_without_a_handler():
    game = _game()
    holding = _put(game, _holding(PlayerId.P1, "P1-mine", gold_production=3))
    assert effective_gold_production(game, holding) == 3


def test_a_non_producer_yields_zero_with_or_without_wealth_counters():
    game = _game()
    hero = _put(
        game,
        DynastyPersonality(id="P1-hero", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1),
    )
    assert effective_gold_production(game, hero) == 0  # personalities have no gold_production

    # Wealth raises Gold Production; with no such stat there is nothing to raise, so a tokened
    # personality must not become a bowable gold source.
    hero.adjust_counter("wealth", 2)
    assert effective_gold_production(game, hero) == 0


def test_a_registered_handler_overrides_with_the_live_views_and_targets():
    game = _game()
    me_sh = _put(game, _stronghold(PlayerId.P1, 8))
    opp_sh = _put(game, _stronghold(PlayerId.P2, 5))
    holding = _put(
        game, _holding(PlayerId.P1, "P1-h", printed_id="probe_holding", gold_production=2)
    )

    seen = {}

    @gold_handler("probe_holding")
    def _probe(card, me, opponents, targets):
        seen["call"] = (card, me, opponents, targets)
        return 99

    try:
        result = effective_gold_production(game, holding, targets=(me_sh,))
    finally:
        GOLD_HANDLERS.pop("probe_holding", None)

    assert result == 99
    card, me, opponents, targets = seen["call"]
    assert card is holding
    assert me.stronghold is me_sh
    assert [o.stronghold for o in opponents] == [opp_sh]
    assert targets == (me_sh,)


def _ancestral_estate(seat):
    return _holding(seat, f"{seat.name}-estate", printed_id="ancestral_estate", gold_production=3)


def test_ancestral_estate_gains_a_gold_for_the_second_player():
    game = _game()  # first_player is P1, so P2 went second
    estate = _put(game, _ancestral_estate(PlayerId.P2))
    assert effective_gold_production(game, estate) == 4


def test_ancestral_estate_stays_at_base_for_the_first_player():
    game = _game()
    estate = _put(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3


def test_dockside_market_adds_for_a_port_and_for_another_market():
    game = _game()
    dockside = _put(
        game,
        _holding(
            PlayerId.P1,
            "P1-dockside",
            printed_id="dockside_market",
            keywords=("Market",),
            gold_production=2,
        ),
    )
    assert effective_gold_production(game, dockside) == 2  # alone

    _put(game, _holding(PlayerId.P1, "P1-port", keywords=("Port",)))
    assert effective_gold_production(game, dockside) == 3  # +1 for the Port

    _put(game, _holding(PlayerId.P1, "P1-market2", keywords=("Market",)))
    assert effective_gold_production(game, dockside) == 4  # +1 for another Market


def _jade_works(seat):
    return _holding(
        seat,
        f"{seat.name}-jadeworks",
        printed_id="jade_works",
        keywords=("Jade",),
        gold_production=3,
    )


def test_jade_works_adds_two_when_paying_for_a_jade_card():
    game = _game()
    works = _put(game, _jade_works(PlayerId.P1))
    jade_target = _holding(PlayerId.P1, "a-jade-card", keywords=("Jade",))
    produced = effective_gold_production(game, works, targets=(jade_target,))
    assert produced == works.gold_production + 2


def test_jade_works_produces_its_base_for_a_non_jade_card():
    game = _game()
    works = _put(game, _jade_works(PlayerId.P1))
    plain = _holding(PlayerId.P1, "a-plain-card", keywords=())
    assert effective_gold_production(game, works, targets=(plain,)) == 3


def test_jade_works_produces_its_base_with_no_target():
    game = _game()
    works = _put(game, _jade_works(PlayerId.P1))
    assert effective_gold_production(game, works) == 3


def _shrine(seat):
    return _holding(
        seat, f"{seat.name}-shrine", printed_id="shrine_of_sincerity", keywords=("Temple",)
    )


def test_shrine_of_sincerity_adds_one_for_a_token_bearing_sincerity_card():
    game = _game()
    shrine = _put(game, _shrine(PlayerId.P1))
    target = _holding(PlayerId.P1, "a-sincerity-card", keywords=("Sincerity",))
    target.adjust_counter("sincerity", 2)
    assert effective_gold_production(game, shrine, targets=(target,)) == shrine.gold_production + 1


def test_shrine_produces_its_base_for_a_sincerity_card_without_tokens():
    game = _game()
    shrine = _put(game, _shrine(PlayerId.P1))
    target = _holding(PlayerId.P1, "a-sincerity-card", keywords=("Sincerity",))  # no tokens
    assert effective_gold_production(game, shrine, targets=(target,)) == 2


def test_shrine_produces_its_base_for_a_token_bearing_non_sincerity_card():
    game = _game()
    shrine = _put(game, _shrine(PlayerId.P1))
    plain = _holding(PlayerId.P1, "a-plain-card", keywords=())
    plain.adjust_counter("sincerity", 2)  # tokens but not a Sincerity card
    assert effective_gold_production(game, shrine, targets=(plain,)) == 2


def test_wealth_counters_raise_printed_production():
    game = _game()
    # A Rice-Farm-style holding: printed 0, so only its Wealth tokens make it a producer at all.
    farm = _put(game, _holding(PlayerId.P1, "P1-farm", gold_production=0))
    assert effective_gold_production(game, farm) == 0

    farm.adjust_counter("wealth", 2)
    assert effective_gold_production(game, farm) == 2


def test_wealth_counters_stack_on_a_handler_card():
    game = _game()
    estate = _put(game, _ancestral_estate(PlayerId.P2))  # second player: handler grants +1
    estate.adjust_counter("wealth", 1)
    assert effective_gold_production(game, estate) == 5  # printed 3 + second-player 1 + wealth 1


def _clan_stronghold(seat, clan):
    return StrongholdCard(
        id=f"{seat.name}-SH", name="SH", side=Side.STRONGHOLD, owner=seat, clan=clan
    )


def test_teardrop_island_produces_three_for_mantis_two_otherwise():
    mantis = _game()
    _put(mantis, _clan_stronghold(PlayerId.P1, "Mantis"))
    at_mantis = _put(
        mantis, _holding(PlayerId.P1, "tm", printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(mantis, at_mantis) == 3

    other = _game()
    _put(other, _clan_stronghold(PlayerId.P1, "Crab"))
    off_clan = _put(
        other, _holding(PlayerId.P1, "to", printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(other, off_clan) == 2
