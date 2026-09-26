from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.engine.zones import FocusZone

from tests.yasuki_core.engine.builders import fate_card, register

P1, P2 = PlayerId.P1, PlayerId.P2


def test_a_table_starts_with_no_focusing_area():
    table = TableState.empty_two_seat()

    assert not [key for key in table.zones if key.role is ZoneRole.FOCUS]


def test_creating_a_focusing_area_is_idempotent():
    table = TableState.empty_two_seat()

    key = ops.create_focus_area(table, P1)
    zone = table.zones[key]

    assert key == ZoneKey(P1, ZoneRole.FOCUS)
    assert isinstance(zone, FocusZone)
    assert zone.owner is P1
    # A second call keeps the cards the first one's zone is already holding.
    assert ops.create_focus_area(table, P1) == key
    assert table.zones[key] is zone


def test_each_seat_focuses_into_its_own_area():
    table = TableState.empty_two_seat()

    ops.create_focus_area(table, P1)
    ops.create_focus_area(table, P2)
    card = register(table, fate_card("f1", P1))
    ops.move_card(table, card, ZoneKey(P1, ZoneRole.FOCUS))

    assert [held.id for held in table.zones[ZoneKey(P1, ZoneRole.FOCUS)].cards] == ["f1"]
    assert table.zones[ZoneKey(P2, ZoneRole.FOCUS)].cards == []
    table.validate()


def test_removing_a_focusing_area_hands_back_what_was_focused():
    table = TableState.empty_two_seat()
    ops.create_focus_area(table, P1)
    card = register(table, fate_card("f1", P1))
    ops.move_card(table, card, ZoneKey(P1, ZoneRole.FOCUS))

    left = ops.remove_focus_area(table, P1)

    assert [held.id for held in left] == ["f1"]
    assert ZoneKey(P1, ZoneRole.FOCUS) not in table.zones


def test_removing_an_area_a_seat_never_had_is_no_error():
    table = TableState.empty_two_seat()

    assert ops.remove_focus_area(table, P1) == []
