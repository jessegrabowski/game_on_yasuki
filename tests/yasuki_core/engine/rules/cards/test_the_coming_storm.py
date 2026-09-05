from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import ability_for, can_pay
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.economy import (
    effective_gold_production,
    effective_province_strength,
    effective_recruit_discount,
)
from yasuki_core.engine.rules.legality import recruit_cost
from yasuki_core.engine.rules.effects import TakeFavor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import IMPERIAL_FAVOR_ID, Side
from yasuki_core.game_pieces.prints import FatePrint, StrongholdPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
)

P1 = PlayerId.P1
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)


def _memorial_game() -> EngineSession:
    """Defensive Memorial face-up in P1's first Province, with gold enough to Recruit it."""
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        register(
            state,
            L5RCard.of(
                StrongholdPrint,
                id="P1-SH",
                name="SH",
                side=Side.STRONGHOLD,
                owner=P1,
                gold_production=8,
                province_strength=3,
            ),
        ),
    )
    memorial = register(
        state,
        holding(
            "memorial",
            printed_id="defensive_memorial",
            owner=P1,
            gold_cost=2,
            gold_production=2,
            keywords=("Fortification",),
        ),
    )
    memorial.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(memorial)
    state.zones[FIRST] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


def test_defensive_memorial_adds_two_to_the_province_it_defends():
    session = _memorial_game()
    assert effective_province_strength(session.game, FIRST) == 3

    session.act(P1, Recruit("memorial"))
    pay(session, P1)

    assert session.game.table.province_attachments == {"memorial": FIRST}
    assert effective_province_strength(session.game, FIRST) == 5


def test_defensive_memorial_enters_bowed_and_still_produces_its_gold():
    """Its two other lines need no handler: the rulebook bows a Holding entering play, and
    ":bow:: Produce 2 Gold" is the Gold Production it prints."""
    session = _memorial_game()

    session.act(P1, Recruit("memorial"))
    pay(session, P1)

    memorial = session.game.table.cards_by_id["memorial"]
    assert memorial.bowed
    assert effective_gold_production(session.game, memorial) == 2


def _natsuyo_game(*, holds_favor: bool = True) -> GameState:
    """Doji Natsuyo in play, her controller holding the Imperial Favor unless a test says not."""
    state = TableState.empty_two_seat()
    state.creatable_tokens[IMPERIAL_FAVOR_ID] = FatePrint(
        name="The Imperial Favor", side=Side.FATE, printed_id=IMPERIAL_FAVOR_ID
    )
    put_in_play(
        state, register(state, personality("natsuyo", printed_id="doji_natsuyo", gold_cost=5))
    )
    game = GameState.start(state, P1, seed=0)
    if holds_favor:
        TakeFavor(P1).perform(game)
    return game


def _natsuyo_ability(game: GameState):
    natsuyo = game.table.cards_by_id["natsuyo"]
    return natsuyo, ability_for(natsuyo, None)


def test_doji_natsuyo_discards_the_favor_to_gain_an_honor():
    """ShE: "Political Open, :bow:, :favor:: Gain 1 Honor." The Favor is half the cost, so it goes
    when the ability is taken and does not pass to anyone."""
    game = _natsuyo_game()
    natsuyo, ability = _natsuyo_ability(game)

    resolve_effects(game, [*ability.cost(game, natsuyo), *ability.effects(game, natsuyo, natsuyo)])

    assert game.table.seats[P1].honor == 1
    assert natsuyo.bowed
    assert game.favor_holder is None


def test_doji_natsuyo_cannot_pay_without_the_favor():
    """Bowing alone does not buy it. Nothing else in play can pay a Favor cost here, so the whole
    cost is unpayable and the ability is never offered."""
    game = _natsuyo_game(holds_favor=False)
    natsuyo, ability = _natsuyo_ability(game)

    assert not can_pay(game, natsuyo, ability.cost)


def test_doji_natsuyo_costs_a_gold_less_against_a_scorpion():
    """ "Natsuyo enters play for :g1: less if another player is Scorpion Clan." """
    game = _natsuyo_game()
    natsuyo = game.table.cards_by_id["natsuyo"]
    put_in_play(game.table, register(game.table, stronghold(PlayerId.P2, clan=ruleset.SCORPION)))

    assert effective_recruit_discount(game, natsuyo) == 1
    assert recruit_cost(game, natsuyo) == 4


def test_doji_natsuyo_is_not_discounted_by_her_own_players_clan():
    """ "another player" — a Crane player who is themselves Scorpion (or the only Scorpion at the
    table) pays her in full."""
    game = _natsuyo_game()
    natsuyo = game.table.cards_by_id["natsuyo"]
    put_in_play(game.table, register(game.table, stronghold(P1, clan=ruleset.SCORPION)))
    put_in_play(game.table, register(game.table, stronghold(PlayerId.P2, clan=ruleset.CRANE)))

    assert effective_recruit_discount(game, natsuyo) == 0
    assert recruit_cost(game, natsuyo) == 5
