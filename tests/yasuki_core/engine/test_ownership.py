from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    owns_card,
    owns_zone,
    owns_deck,
    zone_owned_by_card,
    zone_accepts,
)
from yasuki_core.engine.zones import HandZone, ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


def _table_with_cards() -> TableState:
    table = TableState.empty_two_seat()
    p1_card = L5RCard(id="p1", name="Mine", side=Side.FATE, owner=PlayerId.P1)
    p2_card = L5RCard(id="p2", name="Theirs", side=Side.FATE, owner=PlayerId.P2)
    public = L5RCard(id="pub", name="Public", side=Side.FATE, owner=None)
    table.cards_by_id = {c.id: c for c in (p1_card, p2_card, public)}
    return table


def test_owns_own_card_not_opponents():
    table = _table_with_cards()
    assert owns_card(table, PlayerId.P1, "p1") is True
    assert owns_card(table, PlayerId.P1, "p2") is False
    assert owns_card(table, PlayerId.P2, "p2") is True


def test_public_card_is_actionable_by_either_seat():
    table = _table_with_cards()
    assert owns_card(table, PlayerId.P1, "pub") is True
    assert owns_card(table, PlayerId.P2, "pub") is True


def test_unknown_card_is_denied():
    table = _table_with_cards()
    assert owns_card(table, PlayerId.P1, "ghost") is False


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
    p1_card = L5RCard(id="a", name="A", side=Side.FATE, owner=PlayerId.P1)
    p2_card = L5RCard(id="b", name="B", side=Side.FATE, owner=PlayerId.P2)
    public_card = L5RCard(id="c", name="C", side=Side.FATE, owner=None)
    assert zone_owned_by_card(p1_zone, p1_card) is True
    assert zone_owned_by_card(p1_zone, p2_card) is False
    assert zone_owned_by_card(p1_zone, public_card) is True


def test_zone_accepts_enforces_side():
    hand = HandZone(owner=PlayerId.P1)  # fate-only
    fate = L5RCard(id="f", name="F", side=Side.FATE)
    dynasty = L5RCard(id="d", name="D", side=Side.DYNASTY)
    assert zone_accepts(hand, fate) is True
    assert zone_accepts(hand, dynasty) is False


def test_zone_accepts_enforces_capacity():
    province = ProvinceZone(owner=PlayerId.P1)  # capacity 1, dynasty-only
    first = L5RCard(id="d1", name="D1", side=Side.DYNASTY)
    second = L5RCard(id="d2", name="D2", side=Side.DYNASTY)
    assert zone_accepts(province, first) is True
    province.add(first)
    assert zone_accepts(province, second) is False
