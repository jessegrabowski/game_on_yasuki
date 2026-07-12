import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


def test_empty_two_seat_has_both_seats_and_fixed_zones():
    table = TableState.empty_two_seat("Ada", "Kenji")

    assert set(table.seats) == {PlayerId.P1, PlayerId.P2}
    assert table.seats[PlayerId.P1].name == "Ada"
    assert table.seats[PlayerId.P2].name == "Kenji"
    for seat_info in table.seats.values():
        assert seat_info.honor == 0
        assert not seat_info.ready
        assert not seat_info.connected

    for seat in PlayerId:
        for role in (
            ZoneRole.HAND,
            ZoneRole.FATE_DISCARD,
            ZoneRole.FATE_BANISH,
            ZoneRole.DYNASTY_DISCARD,
            ZoneRole.DYNASTY_BANISH,
        ):
            zone = table.zones[ZoneKey(seat, role)]
            assert zone.owner is seat
        assert DeckKey(seat, Side.FATE) in table.decks
        assert DeckKey(seat, Side.DYNASTY) in table.decks

    # No provinces until CREATE_PROVINCE; battlefield and index start empty.
    assert not any(k.role is ZoneRole.PROVINCE for k in table.zones)
    assert table.battlefield.cards == []
    assert table.cards_by_id == {}
    assert table.seq == 0


def test_empty_table_passes_validation():
    TableState.empty_two_seat().validate()


def test_validate_accepts_a_populated_table():
    table = TableState.empty_two_seat()
    in_hand = L5RCard(id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
    on_board = L5RCard(id="d1", name="Dynasty", side=Side.DYNASTY, owner=PlayerId.P1)

    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(in_hand)
    table.battlefield.add(on_board)
    table.positions[on_board.id] = BoardPos(120.0, 240.0)
    table.cards_by_id = {in_hand.id: in_hand, on_board.id: on_board}

    table.validate()


def test_validate_rejects_duplicate_card_ids():
    table = TableState.empty_two_seat()
    dup_a = L5RCard(id="x", name="A", side=Side.FATE, owner=PlayerId.P1)
    dup_b = L5RCard(id="x", name="B", side=Side.DYNASTY, owner=PlayerId.P1)
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(dup_a)
    table.battlefield.add(dup_b)
    table.cards_by_id = {"x": dup_a}

    with pytest.raises(ValueError, match="Duplicate card id"):
        table.validate()


def test_validate_rejects_index_out_of_sync():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
    table.battlefield.add(card)
    # card present on the board but missing from the identity map

    with pytest.raises(ValueError, match="out of sync"):
        table.validate()


def test_validate_rejects_position_for_non_battlefield_card():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)
    table.cards_by_id = {card.id: card}
    table.positions[card.id] = BoardPos(10.0, 10.0)

    with pytest.raises(ValueError, match="non-battlefield"):
        table.validate()


def test_validate_rejects_province_key_without_idx():
    table = TableState.empty_two_seat()
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE)] = ProvinceZone(owner=PlayerId.P1)

    with pytest.raises(ValueError, match="province zone needs"):
        table.validate()


def test_validate_rejects_idx_on_non_province_key():
    table = TableState.empty_two_seat()
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND, 0)] = table.zones.pop(
        ZoneKey(PlayerId.P1, ZoneRole.HAND)
    )

    with pytest.raises(ValueError, match="must not carry an idx"):
        table.validate()


def test_validate_rejects_zone_owner_mismatch():
    table = TableState.empty_two_seat()
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].owner = PlayerId.P2

    with pytest.raises(ValueError, match="does not match key"):
        table.validate()


def test_validate_rejects_deck_with_non_play_side():
    table = TableState.empty_two_seat()
    table.decks[DeckKey(PlayerId.P1, Side.STRONGHOLD)] = table.decks.pop(
        DeckKey(PlayerId.P1, Side.FATE)
    )

    with pytest.raises(ValueError, match="FATE or DYNASTY"):
        table.validate()


def test_province_zone_keyed_by_idx_validates():
    table = TableState.empty_two_seat()
    for idx in range(4):
        table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, idx)] = ProvinceZone(owner=PlayerId.P1)

    table.validate()


def _put_on_battlefield(table: TableState, card_id: str) -> L5RCard:
    card = L5RCard(id=card_id, name=card_id, side=Side.DYNASTY, owner=PlayerId.P1)
    table.battlefield.add(card)
    table.positions[card_id] = BoardPos(0.0, 0.0)
    table.cards_by_id[card_id] = card
    return card


def test_validate_accepts_card_and_province_attachments():
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "parent")
    _put_on_battlefield(table, "child")
    _put_on_battlefield(table, "fort")
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    table.attachments = {"child": "parent", "fort": province}

    table.validate()


def test_validate_rejects_attachment_child_off_the_battlefield():
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "parent")
    table.attachments = {"ghost": "parent"}

    with pytest.raises(ValueError, match="attachment child not on battlefield"):
        table.validate()


def test_validate_rejects_attachment_to_a_non_battlefield_card():
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "child")
    table.attachments = {"child": "ghost"}

    with pytest.raises(ValueError, match="non-battlefield card"):
        table.validate()


def test_validate_rejects_attachment_to_a_missing_province():
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "child")
    table.attachments = {"child": ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)}

    with pytest.raises(ValueError, match="missing province"):
        table.validate()


def test_validate_rejects_an_attachment_cycle():
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "a")
    _put_on_battlefield(table, "b")
    table.attachments = {"a": "b", "b": "a"}

    with pytest.raises(ValueError, match="cycle"):
        table.validate()
