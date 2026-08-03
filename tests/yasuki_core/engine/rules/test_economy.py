from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import (
    GOLD_HANDLERS,
    effective_gold_production,
    gold_handler,
    opposing_states,
    player_state,
)
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyPersonality
from yasuki_core.game_pieces.pregame import StrongholdCard

from tests.yasuki_core.engine.builders import two_seat_game

from tests.yasuki_core.engine.builders import holding, put_in_play, stronghold


def test_player_state_exposes_stronghold_holdings_gold_and_honor():
    game = two_seat_game()
    sh = put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    market = put_in_play(game, holding("P1-market", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(
        game, stronghold(PlayerId.P2, gold_production=5)
    )  # an opponent's card must not leak into me.in_play
    game.table.seats[PlayerId.P1].honor = 12
    game.gold[PlayerId.P1] = 3

    me = player_state(game, PlayerId.P1)

    assert me.stronghold is sh
    assert me.holdings == (market,)
    assert me.gold == 3 and me.honor == 12
    assert set(me.in_play) == {sh, market}


def test_went_second_is_true_only_for_the_non_first_player():
    game = two_seat_game()  # first_player is P1
    assert player_state(game, PlayerId.P1).went_second is False
    assert player_state(game, PlayerId.P2).went_second is True


def test_controls_matches_a_keyword_and_can_exclude_a_card():
    game = two_seat_game()
    dockside = put_in_play(game, holding("P1-dockside", owner=PlayerId.P1, keywords=("Market",)))
    put_in_play(game, holding("P1-other-market", owner=PlayerId.P1, keywords=("Market",)))

    me = player_state(game, PlayerId.P1)

    assert me.controls("Market") is True
    assert me.controls("Port") is False
    # "another Market" — excluding the asking card still finds the second one.
    assert me.controls("Market", other_than=dockside) is True


def test_controls_other_than_the_only_match_is_false():
    game = two_seat_game()
    lone = put_in_play(game, holding("P1-lone", owner=PlayerId.P1, keywords=("Market",)))
    me = player_state(game, PlayerId.P1)
    assert me.controls("Market", other_than=lone) is False


def test_opposing_states_are_every_other_seat():
    game = two_seat_game()
    put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    opp_sh = put_in_play(game, stronghold(PlayerId.P2, gold_production=5))

    opponents = opposing_states(game, PlayerId.P1)

    assert [o.seat for o in opponents] == [PlayerId.P2]
    assert opponents[0].stronghold is opp_sh


def test_effective_gold_production_falls_back_to_printed_without_a_handler():
    game = two_seat_game()
    mine = put_in_play(game, holding("P1-mine", owner=PlayerId.P1, gold_production=3))
    assert effective_gold_production(game, mine) == 3


def test_a_non_producer_yields_zero_with_or_without_wealth_counters():
    game = two_seat_game()
    hero = put_in_play(
        game,
        DynastyPersonality(id="P1-hero", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1),
    )
    assert effective_gold_production(game, hero) == 0  # personalities have no gold_production

    # Wealth raises Gold Production; with no such stat there is nothing to raise, so a tokened
    # personality must not become a bowable gold source.
    hero.adjust_counter("wealth", 2)
    assert effective_gold_production(game, hero) == 0


def test_a_registered_handler_overrides_with_the_live_views_and_targets():
    game = two_seat_game()
    me_sh = put_in_play(game, stronghold(PlayerId.P1, gold_production=8))
    opp_sh = put_in_play(game, stronghold(PlayerId.P2, gold_production=5))
    probe = put_in_play(
        game, holding("P1-h", owner=PlayerId.P1, printed_id="probe_holding", gold_production=2)
    )

    seen = {}

    @gold_handler("probe_holding")
    def _probe(card, me, opponents, targets):
        seen["call"] = (card, me, opponents, targets)
        return 99

    try:
        result = effective_gold_production(game, probe, targets=(me_sh,))
    finally:
        GOLD_HANDLERS.pop("probe_holding", None)

    assert result == 99
    card, me, opponents, targets = seen["call"]
    assert card is probe
    assert me.stronghold is me_sh
    assert [o.stronghold for o in opponents] == [opp_sh]
    assert targets == (me_sh,)


def _ancestral_estate(seat):
    return holding(
        f"{seat.name}-estate", owner=seat, printed_id="ancestral_estate", gold_production=3
    )


def test_ancestral_estate_gains_a_gold_for_the_second_player():
    game = two_seat_game()  # first_player is P1, so P2 went second
    estate = put_in_play(game, _ancestral_estate(PlayerId.P2))
    assert effective_gold_production(game, estate) == 4


def test_ancestral_estate_stays_at_base_for_the_first_player():
    game = two_seat_game()
    estate = put_in_play(game, _ancestral_estate(PlayerId.P1))
    assert effective_gold_production(game, estate) == 3


def test_dockside_market_adds_for_a_port_and_for_another_market():
    game = two_seat_game()
    dockside = put_in_play(
        game,
        holding(
            "P1-dockside",
            owner=PlayerId.P1,
            printed_id="dockside_market",
            keywords=("Market",),
            gold_production=2,
        ),
    )
    assert effective_gold_production(game, dockside) == 2  # alone

    put_in_play(game, holding("P1-port", owner=PlayerId.P1, keywords=("Port",)))
    assert effective_gold_production(game, dockside) == 3  # +1 for the Port

    put_in_play(game, holding("P1-market2", owner=PlayerId.P1, keywords=("Market",)))
    assert effective_gold_production(game, dockside) == 4  # +1 for another Market


def _jade_works(seat):
    return holding(
        f"{seat.name}-jadeworks",
        owner=seat,
        printed_id="jade_works",
        keywords=("Jade",),
        gold_production=3,
    )


def test_jade_works_adds_two_when_paying_for_a_jade_card():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    jade_target = holding("a-jade-card", owner=PlayerId.P1, keywords=("Jade",))
    produced = effective_gold_production(game, works, targets=(jade_target,))
    assert produced == works.gold_production + 2


def test_jade_works_produces_its_base_for_a_non_jade_card():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    plain = holding("a-plain-card", owner=PlayerId.P1, keywords=())
    assert effective_gold_production(game, works, targets=(plain,)) == 3


def test_jade_works_produces_its_base_with_no_target():
    game = two_seat_game()
    works = put_in_play(game, _jade_works(PlayerId.P1))
    assert effective_gold_production(game, works) == 3


def _shrine(seat):
    return holding(
        f"{seat.name}-shrine",
        owner=seat,
        printed_id="shrine_of_sincerity",
        keywords=("Temple",),
        gold_production=2,  # the base its Sincerity bonus is measured against
    )


def test_shrine_of_sincerity_adds_one_for_a_token_bearing_sincerity_card():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    target = holding("a-sincerity-card", owner=PlayerId.P1, keywords=("Sincerity",))
    target.adjust_counter("sincerity", 2)
    assert effective_gold_production(game, shrine, targets=(target,)) == shrine.gold_production + 1


def test_shrine_produces_its_base_for_a_sincerity_card_without_tokens():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    target = holding("a-sincerity-card", owner=PlayerId.P1, keywords=("Sincerity",))  # no tokens
    assert effective_gold_production(game, shrine, targets=(target,)) == 2


def test_shrine_produces_its_base_for_a_token_bearing_non_sincerity_card():
    game = two_seat_game()
    shrine = put_in_play(game, _shrine(PlayerId.P1))
    plain = holding("a-plain-card", owner=PlayerId.P1, keywords=())
    plain.adjust_counter("sincerity", 2)  # tokens but not a Sincerity card
    assert effective_gold_production(game, shrine, targets=(plain,)) == 2


def test_wealth_counters_raise_printed_production():
    game = two_seat_game()
    # A Rice-Farm-style holding: printed 0, so only its Wealth tokens make it a producer at all.
    farm = put_in_play(game, holding("P1-farm", owner=PlayerId.P1, gold_production=0))
    assert effective_gold_production(game, farm) == 0

    farm.adjust_counter("wealth", 2)
    assert effective_gold_production(game, farm) == 2


def test_wealth_counters_stack_on_a_handler_card():
    game = two_seat_game()
    estate = put_in_play(game, _ancestral_estate(PlayerId.P2))  # second player: handler grants +1
    estate.adjust_counter("wealth", 1)
    assert effective_gold_production(game, estate) == 5  # printed 3 + second-player 1 + wealth 1


def _clan_stronghold(seat, clan):
    return StrongholdCard(
        id=f"{seat.name}-SH", name="SH", side=Side.STRONGHOLD, owner=seat, clan=clan
    )


def test_teardrop_island_produces_three_for_mantis_two_otherwise():
    mantis = two_seat_game()
    put_in_play(mantis, _clan_stronghold(PlayerId.P1, "Mantis"))
    at_mantis = put_in_play(
        mantis, holding("tm", owner=PlayerId.P1, printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(mantis, at_mantis) == 3

    other = two_seat_game()
    put_in_play(other, _clan_stronghold(PlayerId.P1, "Crab"))
    off_clan = put_in_play(
        other, holding("to", owner=PlayerId.P1, printed_id="teardrop_island", gold_production=0)
    )
    assert effective_gold_production(other, off_clan) == 2
