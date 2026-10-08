from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    controls_card,
    owns_zone,
    owns_deck,
    zone_owned_by_card,
    zone_accepts,
)
from yasuki_core.engine.zones import HandZone, ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint


def _table_with_cards() -> TableState:
    table = TableState.empty_two_seat()
    p1_card = L5RCard.of(
        CardPrint, id="p1", printed_id="p1", name="Mine", side=Side.FATE, owner=PlayerId.P1
    )
    p2_card = L5RCard.of(
        CardPrint, id="p2", printed_id="p2", name="Theirs", side=Side.FATE, owner=PlayerId.P2
    )
    table.cards_by_id = {c.id: c for c in (p1_card, p2_card)}
    return table


def test_controls_own_card_not_opponents():
    table = _table_with_cards()
    assert controls_card(table, PlayerId.P1, "p1") is True
    assert controls_card(table, PlayerId.P1, "p2") is False
    assert controls_card(table, PlayerId.P2, "p2") is True


def test_a_card_in_play_is_acted_on_by_its_controller_not_its_owner():
    """The gate follows control, which is the whole of the difference between it and ownership
    (CR, Card control)."""
    table = _table_with_cards()
    mine = table.cards_by_id["p1"]
    table.battlefield.add(mine)
    table.controllers[mine.id] = PlayerId.P2

    assert controls_card(table, PlayerId.P1, "p1") is False
    assert controls_card(table, PlayerId.P2, "p1") is True


def test_unknown_card_is_denied():
    table = _table_with_cards()
    assert controls_card(table, PlayerId.P1, "ghost") is False


def test_owns_own_zone_not_opponents():
    table = TableState.empty_two_seat()
    p1_hand = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    p2_hand = ZoneKey(PlayerId.P2, ZoneRole.HAND)
    assert owns_zone(table, PlayerId.P1, p1_hand) is True
    assert owns_zone(table, PlayerId.P1, p2_hand) is False
    assert owns_zone(table, PlayerId.P2, p2_hand) is True


def test_public_zone_is_actionable_by_either_seat():
    table = TableState.empty_two_seat()
    public_zone = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[public_zone] = ProvinceZone(owner=None)
    assert owns_zone(table, PlayerId.P1, public_zone) is True
    assert owns_zone(table, PlayerId.P2, public_zone) is True


def test_unknown_zone_is_denied():
    table = TableState.empty_two_seat()
    assert owns_zone(table, PlayerId.P1, ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 9)) is False


def test_owns_own_deck_not_opponents():
    table = TableState.empty_two_seat()
    assert owns_deck(table, PlayerId.P1, DeckKey(PlayerId.P1, Side.FATE)) is True
    assert owns_deck(table, PlayerId.P1, DeckKey(PlayerId.P2, Side.FATE)) is False
    assert owns_deck(table, PlayerId.P2, DeckKey(PlayerId.P2, Side.DYNASTY)) is True


def test_zone_owned_by_card_blocks_cross_owner():
    p1_zone = HandZone(owner=PlayerId.P1)
    p1_card = L5RCard.of(
        CardPrint, id="a", printed_id="a", name="A", side=Side.FATE, owner=PlayerId.P1
    )
    p2_card = L5RCard.of(
        CardPrint, id="b", printed_id="b", name="B", side=Side.FATE, owner=PlayerId.P2
    )
    assert zone_owned_by_card(p1_zone, p1_card) is True
    assert zone_owned_by_card(p1_zone, p2_card) is False


def test_zone_accepts_enforces_side():
    hand = HandZone(owner=PlayerId.P1)  # fate-only
    fate = L5RCard.of(
        CardPrint, id="f", printed_id="f", name="F", side=Side.FATE, owner=PlayerId.P1
    )
    dynasty = L5RCard.of(
        CardPrint, id="d", printed_id="d", name="D", side=Side.DYNASTY, owner=PlayerId.P1
    )
    assert zone_accepts(hand, fate) is True
    assert zone_accepts(hand, dynasty) is False


def test_zone_accepts_enforces_capacity():
    province = ProvinceZone(owner=PlayerId.P1)  # capacity 1, dynasty-only
    first = L5RCard.of(
        CardPrint, id="d1", printed_id="d1", name="D1", side=Side.DYNASTY, owner=PlayerId.P1
    )
    second = L5RCard.of(
        CardPrint, id="d2", printed_id="d2", name="D2", side=Side.DYNASTY, owner=PlayerId.P1
    )
    assert zone_accepts(province, first) is True
    province.add(first)
    assert zone_accepts(province, second) is False
