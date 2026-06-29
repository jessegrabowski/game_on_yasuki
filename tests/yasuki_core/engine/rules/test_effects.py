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


def test_effective_gold_production_of_a_non_producer_is_zero():
    game = _game()
    hero = _put(
        game,
        DynastyPersonality(id="P1-hero", name="Hero", side=Side.DYNASTY, owner=PlayerId.P1),
    )
    assert effective_gold_production(game, hero) == 0  # personalities have no gold_production


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


def test_ancestral_estate_gains_a_gold_when_an_opponent_out_produces():
    game = _game()
    estate = _put(game, _ancestral_estate(PlayerId.P1))
    _put(game, _stronghold(PlayerId.P1, 4))
    _put(game, _stronghold(PlayerId.P2, 5))  # out-produces P1's 4
    assert effective_gold_production(game, estate) == 4


def test_ancestral_estate_stays_at_base_when_no_opponent_out_produces():
    game = _game()
    estate = _put(game, _ancestral_estate(PlayerId.P1))
    _put(game, _stronghold(PlayerId.P1, 4))
    _put(game, _stronghold(PlayerId.P2, 4))  # equal GP ties, so it does not out-produce (strict >)
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
