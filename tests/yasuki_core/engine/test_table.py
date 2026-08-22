import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
    Location,
    unit_members,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint, PersonalityPrint


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
    in_hand = L5RCard.of(CardPrint, id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
    on_board = L5RCard.of(CardPrint, id="d1", name="Dynasty", side=Side.DYNASTY, owner=PlayerId.P1)

    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(in_hand)
    table.battlefield.add(on_board)
    table.positions[on_board.id] = BoardPos(120.0, 240.0)
    table.cards_by_id = {in_hand.id: in_hand, on_board.id: on_board}

    table.validate()


def test_validate_rejects_duplicate_card_ids():
    table = TableState.empty_two_seat()
    dup_a = L5RCard.of(CardPrint, id="x", name="A", side=Side.FATE, owner=PlayerId.P1)
    dup_b = L5RCard.of(CardPrint, id="x", name="B", side=Side.DYNASTY, owner=PlayerId.P1)
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(dup_a)
    table.battlefield.add(dup_b)
    table.cards_by_id = {"x": dup_a}

    with pytest.raises(ValueError, match="Duplicate card id"):
        table.validate()


def test_validate_rejects_index_out_of_sync():
    table = TableState.empty_two_seat()
    card = L5RCard.of(CardPrint, id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
    table.battlefield.add(card)
    # card present on the board but missing from the identity map

    with pytest.raises(ValueError, match="out of sync"):
        table.validate()


def test_validate_rejects_position_for_non_battlefield_card():
    table = TableState.empty_two_seat()
    card = L5RCard.of(CardPrint, id="f1", name="Fate", side=Side.FATE, owner=PlayerId.P1)
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
    card = L5RCard.of(CardPrint, id=card_id, name=card_id, side=Side.DYNASTY, owner=PlayerId.P1)
    table.battlefield.add(card)
    table.positions[card_id] = BoardPos(0.0, 0.0)
    table.cards_by_id[card_id] = card
    return card


def _put_personality_on_battlefield(table: TableState, card_id: str) -> L5RCard:
    card = L5RCard.of(
        PersonalityPrint, id=card_id, name=card_id, side=Side.DYNASTY, owner=PlayerId.P1
    )
    table.battlefield.add(card)
    table.positions[card_id] = BoardPos(0.0, 0.0)
    table.cards_by_id[card_id] = card
    return card


def test_validate_accepts_a_unit_and_a_province_attachment():
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    _put_on_battlefield(table, "item")
    _put_on_battlefield(table, "fort")
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    table.units = {"item": "hero"}
    table.province_attachments = {"fort": province}

    table.validate()


def test_validate_rejects_a_unit_parent_that_is_not_a_personality():
    """Attachments are the only card type that may attach to a Personality, and a Personality is the
    only thing they may attach to (CR, Attachments) — so a Follower parent is not a board state to
    tolerate, it is a broken relation."""
    table = TableState.empty_two_seat()
    _put_on_battlefield(table, "follower")
    _put_on_battlefield(table, "item")
    table.units = {"item": "follower"}

    with pytest.raises(ValueError, match="not a Personality"):
        table.validate()


def test_validate_rejects_a_unit_member_off_the_battlefield():
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    table.units = {"ghost": "hero"}

    with pytest.raises(ValueError, match="unit member not on battlefield"):
        table.validate()


def test_validate_rejects_a_card_both_in_a_unit_and_on_a_province():
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    _put_on_battlefield(table, "item")
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    table.units = {"item": "hero"}
    table.province_attachments = {"item": province}

    with pytest.raises(ValueError, match="in a unit and on a province"):
        table.validate()


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


def test_validate_accepts_a_unit_at_a_battlefield():
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    _put_on_battlefield(table, "ashigaru")
    table.units = {"ashigaru": "hero"}
    table.locations = {
        "hero": Location.at_battlefield(0),
        "ashigaru": Location.at_battlefield(0),
    }

    table.validate()


def test_validate_rejects_a_location_for_a_card_not_in_play():
    table = TableState.empty_two_seat()
    table.locations = {"ghost": Location.at_battlefield(0)}

    with pytest.raises(ValueError, match="locations reference cards not in play"):
        table.validate()


@pytest.mark.parametrize(
    "location",
    [Location(), Location(seat=PlayerId.P1, battlefield=0)],
    ids=["neither", "both"],
)
def test_validate_rejects_a_location_naming_neither_or_both(location):
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    table.locations = {"hero": location}

    with pytest.raises(ValueError, match="names neither a home nor a battlefield"):
        table.validate()


def test_validate_rejects_a_home_belonging_to_no_seat():
    """A location may name a home the table has no seat for — a stale seat left behind by a table
    rebuilt with different players — and that is a broken relation rather than a card at home."""
    table = TableState.empty_two_seat()
    _put_personality_on_battlefield(table, "hero")
    del table.seats[PlayerId.P2]
    table.locations = {"hero": Location.home(PlayerId.P2)}

    with pytest.raises(ValueError, match="has unknown seat"):
        table.validate()


def test_unit_members_lead_with_the_personality():
    table = TableState.empty_two_seat()
    hero = _put_personality_on_battlefield(table, "hero")
    _put_on_battlefield(table, "ashigaru")
    _put_on_battlefield(table, "blade")
    table.units = {"ashigaru": "hero", "blade": "hero"}

    members = unit_members(table, hero)

    assert members[0] is hero
    assert {card.id for card in members} == {"hero", "ashigaru", "blade"}


def test_unit_members_of_a_bare_card_is_that_card_alone():
    table = TableState.empty_two_seat()
    hero = _put_personality_on_battlefield(table, "hero")

    assert unit_members(table, hero) == [hero]


def test_unit_members_excludes_another_personalitys_attachments():
    table = TableState.empty_two_seat()
    hero = _put_personality_on_battlefield(table, "hero")
    _put_personality_on_battlefield(table, "rival")
    _put_on_battlefield(table, "theirs")
    table.units = {"theirs": "rival"}

    assert unit_members(table, hero) == [hero]
