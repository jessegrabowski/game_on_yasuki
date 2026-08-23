from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_gold_production, effective_province_strength
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import end_phase, holding, put_in_play, register

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
    session.submit(P1, DecisionResponse(("P1-SH",)))

    assert session.game.table.province_attachments == {"memorial": FIRST}
    assert effective_province_strength(session.game, FIRST) == 5


def test_defensive_memorial_enters_bowed_and_still_produces_its_gold():
    """Its two other lines need no handler: the rulebook bows a Holding entering play, and
    ":bow:: Produce 2 Gold" is the Gold Production it prints."""
    session = _memorial_game()

    session.act(P1, Recruit("memorial"))
    session.submit(P1, DecisionResponse(("P1-SH",)))

    memorial = session.game.table.cards_by_id["memorial"]
    assert memorial.bowed
    assert effective_gold_production(session.game, memorial) == 2
