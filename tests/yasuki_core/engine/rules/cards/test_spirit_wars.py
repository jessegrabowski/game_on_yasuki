from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, Recruit
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import StrongholdPrint

from tests.yasuki_core.engine.builders import end_phase, holding, pay, put_in_play, register

P1 = PlayerId.P1
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)


def _garden_game(printed_id: str = "poorly_placed_garden") -> EngineSession:
    """A Holding face-up in P1's first Province, with gold enough to Recruit it."""
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
            ),
        ),
    )
    garden = register(
        state,
        holding(
            "garden", printed_id=printed_id, owner=P1, gold_cost=5, keywords=("Fortification",)
        ),
    )
    garden.turn_face_up()
    province = ProvinceZone(owner=P1)
    province.add(garden)
    state.zones[FIRST] = province
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    session.act(P1, Recruit("garden"))
    pay(session, P1)
    return session


def test_poorly_placed_garden_enters_play_unbowed():
    """ "Enters play unbowed" overrides the rule that a Holding enters play bowed — and it has to,
    or the Limited ability that bows it as a cost could never be paid the turn it arrives."""
    session = _garden_game()

    assert not session.game.table.cards_by_id["garden"].bowed


def test_a_holding_without_that_text_still_enters_play_bowed():
    """The exception is the card's, not every Fortification's."""
    session = _garden_game(printed_id="plain_fortification")

    assert session.game.table.cards_by_id["garden"].bowed


def test_poorly_placed_garden_bows_itself_for_two_honor():
    # Built in play rather than Recruited: the ability is Limited, so it is offered in the Action
    # phase, and a Recruit happens in the Dynasty phase after it has closed.
    state = TableState.empty_two_seat()
    put_in_play(
        state,
        register(
            state,
            holding("garden", printed_id="poorly_placed_garden", owner=P1, gold_cost=5),
        ),
    )
    session = EngineSession.start(state, P1)

    session.act(P1, ActivateAbility("garden"))

    assert session.game.table.seats[P1].honor == 2
    assert session.game.table.cards_by_id["garden"].bowed
