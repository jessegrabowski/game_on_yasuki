from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.sim.metrics import (
    empty_provinces,
    family_honor,
    potential_gold_production,
    provinces_cleared,
    provinces_held,
)

from tests.yasuki_core.engine.builders import dealt_table, holding, province_card, put_in_play

P1 = PlayerId.P1


def _game(*producers: int) -> EngineSession:
    table = dealt_table()
    for index, production in enumerate(producers):
        put_in_play(table, holding(f"p{index}", owner=P1, gold_production=production))
    return EngineSession.start(table, P1, seed=1)


def test_potential_production_sums_the_seats_producers():
    session = _game(4, 2, 1)

    assert potential_gold_production(session.game, P1) == 7


def test_a_seat_with_no_producers_could_raise_nothing():
    assert potential_gold_production(_game().game, P1) == 0


def test_potential_production_ignores_the_opponents_producers():
    session = _game(4)
    put_in_play(session.game, holding("theirs", owner=PlayerId.P2, gold_production=9))

    assert potential_gold_production(session.game, P1) == 4


def test_potential_production_is_not_the_gold_pool():
    """The pool reads zero at every turn boundary — gold is produced during a payment and cleared
    at the end of the phase. A metric that sampled it would report zero forever and look correct."""
    session = _game(4, 2)

    assert session.game.gold[P1] == 0
    assert potential_gold_production(session.game, P1) == 6


def test_a_producer_bowed_to_pay_stops_counting():
    session = _game(4, 2)
    province_card(session.game, "target", seat=P1, gold_cost=3)
    session.act(P1, Pass())
    session.act(P1, Pass())
    session.act(P1, Recruit("target"))
    agent = AutoAgent()
    while session.game.pending is not None:
        seat = session.game.pending.seat
        session.submit(seat, agent.decide(session.game.pending, session.project(seat)))

    # The 4-producer covered the cost of 3 and bowed; the 2-producer is untouched.
    assert potential_gold_production(session.game, P1) == 2


def test_a_bow_time_boost_is_not_counted():
    """Outlying Farms could raise 4 by boosting, and flow.reachable_gold says so. This metric says
    2, because the boost costs the card its life. Sustainable output is what a deck is judged on,
    and the two functions disagreeing is the intent rather than a bug in either."""
    session = _game()
    put_in_play(
        session.game,
        holding("of", owner=P1, printed_id="outlying_farms", gold_production=2),
    )

    assert potential_gold_production(session.game, P1) == 2


def test_a_target_dependent_producer_reports_its_unconditional_base():
    """Jade Works yields +2 when paying for a Jade card. A metric has no payment in flight, so it
    reports the base — the reason this number can sit below what a given recruit could muster."""
    session = _game()
    put_in_play(
        session.game,
        holding("jw", owner=P1, printed_id="jade_works", gold_production=2),
    )

    assert potential_gold_production(session.game, P1) == 2


def test_family_honor_reads_the_seats_standing_total():
    session = _game()
    ops.set_honor(session.game.table, P1, value=12)

    assert family_honor(session.game, P1) == 12


def test_family_honor_is_read_per_seat():
    session = _game()
    ops.set_honor(session.game.table, P1, value=5)
    ops.set_honor(session.game.table, PlayerId.P2, value=-3)

    assert family_honor(session.game, P1) == 5
    assert family_honor(session.game, PlayerId.P2) == -3


def test_family_honor_can_be_negative():
    # Dishonorable play is a real position, not an error state, so nothing floors this at zero.
    session = _game()
    ops.set_honor(session.game.table, P1, value=2)
    ops.set_honor(session.game.table, P1, delta=-7)

    assert family_honor(session.game, P1) == -5


def test_provinces_held_counts_the_seats_provinces():
    session = _game()
    for index in range(3):
        province_card(session.game, f"card{index}", seat=P1, index=index)

    assert provinces_held(session.game, P1) == 3


def test_a_province_emptied_by_an_exhausted_deck_is_still_held():
    """Held counts the province, not the card in it. Otherwise the denominator would shrink exactly
    as the numerator it normalizes grows, and a seat running out of dynasty deck would look intact."""
    session = _game()
    for index in range(3):
        province_card(session.game, f"card{index}", seat=P1, index=index)
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards.clear()

    assert provinces_held(session.game, P1) == 3
    assert empty_provinces(session.game, P1) == 1


def test_a_seat_holding_no_provinces_is_told_apart_from_one_holding_full_ones():
    """The reason this metric exists. Both boards report zero cleared and zero empty; only the
    denominator says one seat is intact and the other has nothing left."""
    intact = _game()
    for index in range(4):
        province_card(intact.game, f"card{index}", seat=P1, index=index)
    stripped = _game()

    assert (provinces_held(intact.game, P1), provinces_held(stripped.game, P1)) == (4, 0)
    assert provinces_cleared(intact.game, P1) == provinces_cleared(stripped.game, P1) == 0
    assert empty_provinces(intact.game, P1) == empty_provinces(stripped.game, P1) == 0


def test_a_face_down_province_card_counts_as_cleared():
    # Vacating a province refills it face-down, so this is what a cleared one looks like afterwards.
    session = _game()
    province_card(session.game, "refilled", seat=P1, index=0, face_up=False)
    province_card(session.game, "untouched", seat=P1, index=1)

    assert provinces_cleared(session.game, P1) == 1


def test_an_untouched_province_card_is_not_counted():
    session = _game()
    for index in range(3):
        province_card(session.game, f"card{index}", seat=P1, index=index)

    assert provinces_cleared(session.game, P1) == 0


def test_an_empty_province_is_not_counted_as_cleared():
    """The two are separate readings of separate situations: a province with nothing in it was not
    turned over, it ran dry."""
    session = _game()
    province_card(session.game, "card", seat=P1, index=0)
    session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)].cards.clear()

    assert provinces_cleared(session.game, P1) == 0
    assert empty_provinces(session.game, P1) == 1


def test_the_opponents_cleared_provinces_are_not_counted():
    session = _game()
    province_card(session.game, "mine", seat=P1, index=0)
    province_card(session.game, "theirs", seat=PlayerId.P2, index=0, face_up=False)

    assert provinces_cleared(session.game, P1) == 0
    assert provinces_cleared(session.game, PlayerId.P2) == 1


def test_provinces_holding_cards_count_as_none_empty():
    session = _game()
    for index in range(3):
        province_card(session.game, f"card{index}", seat=P1, index=index)

    assert empty_provinces(session.game, P1) == 0


def test_a_province_whose_card_has_gone_counts_as_empty():
    session = _game()
    for index in range(3):
        province_card(session.game, f"card{index}", seat=P1, index=index)
    emptied = session.game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 1)]
    emptied.cards.clear()

    assert empty_provinces(session.game, P1) == 1


def test_the_opponents_empty_provinces_are_not_counted():
    session = _game()
    province_card(session.game, "mine", seat=P1, index=0)
    province_card(session.game, "theirs", seat=PlayerId.P2, index=0)
    session.game.table.zones[ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)].cards.clear()

    assert empty_provinces(session.game, P1) == 0
