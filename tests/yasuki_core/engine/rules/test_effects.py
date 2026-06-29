from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import player_state, opposing_states
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyHolding
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


def _holding(seat, card_id, *, keywords=()):
    return DynastyHolding(
        id=card_id,
        name="H",
        side=Side.DYNASTY,
        owner=seat,
        gold_production=2,
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
