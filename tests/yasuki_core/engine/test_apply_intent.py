import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    ZoneKey,
    ZoneRole,
    DeckKey,
    BoardPos,
    BATTLEFIELD,
    MoveCard,
    SetCardPos,
    Bow,
    Unbow,
    Flip,
    Invert,
    Reveal,
    Hide,
    Draw,
    Shuffle,
    SearchDeck,
    FillProvince,
    DestroyProvince,
    DiscardProvince,
    CreateProvince,
    SetHonor,
    SpawnCard,
    RemoveCard,
    apply_intent,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard
from yasuki_core.game_pieces.fate import FateCard


def _fate(card_id: str, owner: PlayerId = PlayerId.P1) -> FateCard:
    return FateCard(id=card_id, name=card_id, side=Side.FATE, owner=owner)


def _dynasty(card_id: str, owner: PlayerId = PlayerId.P1) -> DynastyCard:
    return DynastyCard(id=card_id, name=card_id, side=Side.DYNASTY, owner=owner)


def _on_battlefield(table: TableState, card: L5RCard, pos: BoardPos = BoardPos(0.0, 0.0)) -> None:
    table.cards_by_id[card.id] = card
    table.battlefield.add(card)
    table.positions[card.id] = pos


def test_move_card_battlefield_to_hand_goes_face_down():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert table.seq == 1
    assert len(events) == 1 and events[0].seq == 1
    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert card not in table.battlefield.cards
    assert "f1" not in table.positions
    assert card.face_up is False


def test_move_card_to_battlefield_sets_position():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", BATTLEFIELD, BoardPos(15.0, 25.0)))

    assert card in table.battlefield.cards
    assert table.positions["f1"] == BoardPos(15.0, 25.0)


def test_move_to_battlefield_without_position_uses_origin():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", BATTLEFIELD))

    assert table.positions["f1"] == BoardPos(0.0, 0.0)


def test_move_within_battlefield_without_position_keeps_existing_spot():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card, BoardPos(7.0, 8.0))

    apply_intent(table, PlayerId.P1, MoveCard("f1", BATTLEFIELD))

    assert table.positions["f1"] == BoardPos(7.0, 8.0)


def test_move_card_to_own_deck_resets_flags():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.bow()
    card.invert()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P1, Side.FATE)))

    assert card in table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards
    assert card.face_up is False
    assert card.bowed is False
    assert card.inverted is False


def test_move_card_rejects_opponents_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P2, ZoneRole.HAND)))

    assert events == []
    assert table.seq == 0
    assert card in table.battlefield.cards


def test_move_card_rejects_wrong_side_for_zone():
    table = TableState.empty_two_seat()
    card = _dynasty("d1")  # dynasty card into a fate-only hand
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, MoveCard("d1", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert events == []
    assert table.seq == 0
    assert card in table.battlefield.cards


def test_move_card_into_empty_province_unbows():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)
    card = _dynasty("d1")
    card.bow()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("d1", province_key))

    assert card in table.zones[province_key].cards
    assert card.bowed is False


def test_move_card_rejects_when_zone_full():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)
    sitting = _dynasty("d0")
    table.cards_by_id["d0"] = sitting
    table.zones[province_key].add(sitting)
    incoming = _dynasty("d1")
    _on_battlefield(table, incoming)

    events = apply_intent(table, PlayerId.P1, MoveCard("d1", province_key))

    assert events == []
    assert incoming in table.battlefield.cards


def test_move_card_into_opponents_deck_rejected():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P2, Side.FATE)))

    assert events == []
    assert card in table.battlefield.cards


def test_set_card_pos_updates_position():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card, BoardPos(1.0, 1.0))

    apply_intent(table, PlayerId.P1, SetCardPos("f1", 9.0, 4.0))

    assert table.positions["f1"] == BoardPos(9.0, 4.0)
    assert table.seq == 1


def test_set_card_pos_no_op_when_unchanged():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card, BoardPos(3.0, 3.0))

    events = apply_intent(table, PlayerId.P1, SetCardPos("f1", 3.0, 3.0))

    assert events == []
    assert table.seq == 0


def test_set_card_pos_rejects_card_not_on_battlefield():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    events = apply_intent(table, PlayerId.P1, SetCardPos("f1", 5.0, 5.0))

    assert events == []
    assert "f1" not in table.positions


def test_set_card_pos_rejects_opponents_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card, BoardPos(1.0, 1.0))

    events = apply_intent(table, PlayerId.P1, SetCardPos("f1", 8.0, 8.0))

    assert events == []
    assert table.positions["f1"] == BoardPos(1.0, 1.0)


def test_bow_sets_flag_and_bumps_seq():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, Bow(("f1",)))

    assert card.bowed is True
    assert table.seq == 1
    assert events[0].cards == ("f1",)


def test_bow_already_bowed_is_no_op():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.bow()
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, Bow(("f1",)))

    assert events == []
    assert table.seq == 0


def test_unbow_clears_flag():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.bow()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, Unbow(("f1",)))

    assert card.bowed is False


def test_flip_toggles_face():
    table = TableState.empty_two_seat()
    card = _fate("f1")  # starts face up
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, Flip(("f1",)))
    assert card.face_up is False
    apply_intent(table, PlayerId.P1, Flip(("f1",)))
    assert card.face_up is True
    assert table.seq == 2


def test_invert_toggles_both_directions():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, Invert(("f1",)))
    assert card.inverted is True
    apply_intent(table, PlayerId.P1, Invert(("f1",)))
    assert card.inverted is False


def test_reveal_and_hide():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, Reveal(("f1",)))
    assert card.revealed is True
    apply_intent(table, PlayerId.P1, Hide(("f1",)))
    assert card.revealed is False


def test_batch_flag_is_atomic_and_rejected_if_any_unowned():
    table = TableState.empty_two_seat()
    mine = _fate("f1", owner=PlayerId.P1)
    theirs = _fate("f2", owner=PlayerId.P2)
    _on_battlefield(table, mine)
    _on_battlefield(table, theirs)

    events = apply_intent(table, PlayerId.P1, Bow(("f1", "f2")))

    assert events == []
    assert mine.bowed is False  # rolled into nothing — neither card touched
    assert theirs.bowed is False
    assert table.seq == 0


def test_batch_flag_applies_to_all_owned():
    table = TableState.empty_two_seat()
    a = _fate("f1")
    b = _fate("f2")
    _on_battlefield(table, a)
    _on_battlefield(table, b)

    events = apply_intent(table, PlayerId.P1, Bow(("f1", "f2")))

    assert a.bowed and b.bowed
    assert set(events[0].cards) == {"f1", "f2"}
    assert table.seq == 1


def test_draw_fate_goes_to_hand_face_up():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards.append(card)

    events = apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.FATE)))

    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert card.face_up is True
    assert isinstance(events[0].intent, MoveCard)
    assert events[0].intent.to == ZoneKey(PlayerId.P1, ZoneRole.HAND)


def test_draw_dynasty_fills_empty_province_face_down():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)
    card = _dynasty("d1")
    table.cards_by_id["d1"] = card
    table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards.append(card)

    events = apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))

    assert card in table.zones[province_key].cards
    assert card.face_up is False
    assert events[0].intent.to == province_key


def test_draw_dynasty_with_no_province_goes_to_battlefield():
    table = TableState.empty_two_seat()
    card = _dynasty("d1")
    table.cards_by_id["d1"] = card
    table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards.append(card)

    events = apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))

    assert card in table.battlefield.cards
    assert table.positions["d1"] == BoardPos(0.0, 0.0)
    assert events[0].intent.to == BATTLEFIELD


def test_draw_from_empty_deck_is_rejected():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.FATE)))
    assert events == []
    assert table.seq == 0


def test_draw_from_opponents_deck_rejected():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.decks[DeckKey(PlayerId.P2, Side.FATE)].cards.append(card)

    events = apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P2, Side.FATE)))

    assert events == []
    assert card in table.decks[DeckKey(PlayerId.P2, Side.FATE)].cards


def test_shuffle_rejects_opponents_deck():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, Shuffle(DeckKey(PlayerId.P2, Side.FATE), seed=1))
    assert events == []
    assert table.seq == 0


def test_search_deck_owner_gets_event_without_seq_bump():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, SearchDeck(DeckKey(PlayerId.P1, Side.DYNASTY)))
    assert len(events) == 1
    assert table.seq == 0  # read-only


def test_search_deck_rejects_opponents_deck():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, SearchDeck(DeckKey(PlayerId.P2, Side.DYNASTY)))
    assert events == []


def test_fill_province_draws_dynasty_face_down():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)
    card = _dynasty("d1")
    table.cards_by_id["d1"] = card
    table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards.append(card)

    apply_intent(table, PlayerId.P1, FillProvince(province_key))

    assert card in table.zones[province_key].cards
    assert card.face_up is False


def test_fill_province_rejects_full_province():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)
    table.zones[province_key].add(_dynasty("d0"))
    spare = _dynasty("d1")
    table.cards_by_id["d1"] = spare
    table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards.append(spare)

    events = apply_intent(table, PlayerId.P1, FillProvince(province_key))

    assert events == []
    assert spare in table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards


def test_destroy_province_discards_face_up_and_removes_zone():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    zone = ProvinceZone(owner=PlayerId.P1)
    card = _dynasty("d1")
    card.turn_face_down()
    table.cards_by_id["d1"] = card
    zone.add(card)
    table.zones[province_key] = zone

    events = apply_intent(table, PlayerId.P1, DestroyProvince(province_key))

    assert province_key not in table.zones
    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert card.face_up is True
    assert events[0].cards == ("d1",)


def test_destroy_empty_province_still_removes_zone():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)

    events = apply_intent(table, PlayerId.P1, DestroyProvince(province_key))

    assert province_key not in table.zones
    assert events[0].cards == ()
    assert table.seq == 1


def test_discard_province_moves_top_to_dynasty_discard():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    zone = ProvinceZone(owner=PlayerId.P1)
    card = _dynasty("d1")
    table.cards_by_id["d1"] = card
    zone.add(card)
    table.zones[province_key] = zone

    apply_intent(table, PlayerId.P1, DiscardProvince(province_key))

    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert card.face_up is True


def test_discard_empty_province_rejected():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P1)

    events = apply_intent(table, PlayerId.P1, DiscardProvince(province_key))

    assert events == []


def test_province_op_rejects_opponents_province():
    table = TableState.empty_two_seat()
    province_key = ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0)
    table.zones[province_key] = ProvinceZone(owner=PlayerId.P2)

    events = apply_intent(table, PlayerId.P1, FillProvince(province_key))

    assert events == []


def test_create_province_allocates_next_index():
    table = TableState.empty_two_seat()

    apply_intent(table, PlayerId.P1, CreateProvince())
    apply_intent(table, PlayerId.P1, CreateProvince())

    assert ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0) in table.zones
    assert ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 1) in table.zones
    assert table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].owner is PlayerId.P1


def test_set_honor_by_delta():
    table = TableState.empty_two_seat()
    table.seats[PlayerId.P1].honor = 10

    apply_intent(table, PlayerId.P1, SetHonor(delta=-3))

    assert table.seats[PlayerId.P1].honor == 7
    assert table.seq == 1


def test_set_honor_by_value():
    table = TableState.empty_two_seat()
    apply_intent(table, PlayerId.P1, SetHonor(value=25))
    assert table.seats[PlayerId.P1].honor == 25


def test_set_honor_no_op_when_unchanged():
    table = TableState.empty_two_seat()
    table.seats[PlayerId.P1].honor = 5

    events = apply_intent(table, PlayerId.P1, SetHonor(value=5))

    assert events == []
    assert table.seq == 0


def test_set_honor_only_affects_acting_seat():
    table = TableState.empty_two_seat()
    apply_intent(table, PlayerId.P2, SetHonor(value=12))
    assert table.seats[PlayerId.P2].honor == 12
    assert table.seats[PlayerId.P1].honor == 0


@pytest.mark.parametrize(
    "intent",
    [
        Bow(("f1",)),
        Flip(("f1",)),
        SetCardPos("f1", 1.0, 1.0),
    ],
)
def test_rejected_intent_leaves_state_unchanged(intent):
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card)
    before_seq = table.seq

    events = apply_intent(table, PlayerId.P1, intent)

    assert events == []
    assert table.seq == before_seq


def test_spawn_card_creates_a_public_face_up_battlefield_card():
    table = TableState.empty_two_seat()
    intent = SpawnCard("tok1", "Bushi Token", Side.DYNASTY, "sets/x/a.jpg", BoardPos(5.0, 6.0))

    events = apply_intent(table, PlayerId.P1, intent)

    assert table.seq == 1 and events[0].cards == ("tok1",)
    card = table.cards_by_id["tok1"]
    assert card.owner is None and card.face_up is True
    assert card in table.battlefield.cards
    assert table.positions["tok1"] == BoardPos(5.0, 6.0)
    table.validate()


def test_spawn_card_rejects_a_duplicate_id():
    table = TableState.empty_two_seat()
    intent = SpawnCard("tok1", "X", Side.FATE, None, BoardPos(0.0, 0.0))
    apply_intent(table, PlayerId.P1, intent)

    assert apply_intent(table, PlayerId.P1, intent) == []


def test_remove_card_takes_a_public_card_off_the_table():
    table = TableState.empty_two_seat()
    apply_intent(table, PlayerId.P1, SpawnCard("tok1", "X", Side.FATE, None, BoardPos(0.0, 0.0)))

    events = apply_intent(table, PlayerId.P2, RemoveCard("tok1"))  # public → either seat may remove

    assert events[0].cards == ("tok1",)
    assert "tok1" not in table.cards_by_id
    assert table.battlefield.cards == []
    assert "tok1" not in table.positions
    table.validate()


def test_remove_card_rejects_an_opponents_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card)

    assert apply_intent(table, PlayerId.P1, RemoveCard("f1")) == []
    assert "f1" in table.cards_by_id


def test_remove_card_rejects_an_unknown_id():
    table = TableState.empty_two_seat()
    assert apply_intent(table, PlayerId.P1, RemoveCard("ghost")) == []


def test_table_invariants_hold_after_a_sequence_of_intents():
    # The handlers' core obligation is to keep cards_by_id and positions consistent as cards move.
    # validate() asserts that whole-table invariant; running it after a representative sequence
    # guards every handler at once (e.g. a position not cleared when a card leaves the battlefield).
    table = TableState.empty_two_seat()
    dynasty_deck = table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    fate_deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    for i in range(3):
        dynasty = _dynasty(f"d{i}")
        fate = _fate(f"f{i}")
        table.cards_by_id[dynasty.id] = dynasty
        table.cards_by_id[fate.id] = fate
        dynasty_deck.cards.append(dynasty)
        fate_deck.cards.append(fate)

    apply_intent(table, PlayerId.P1, CreateProvince())
    apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.DYNASTY)))  # fills province
    apply_intent(table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.FATE)))  # to hand
    apply_intent(
        table, PlayerId.P1, Draw(DeckKey(PlayerId.P1, Side.DYNASTY))
    )  # no province → board
    apply_intent(table, PlayerId.P1, MoveCard("d1", BATTLEFIELD, BoardPos(5.0, 5.0)))
    apply_intent(table, PlayerId.P1, MoveCard("d1", DeckKey(PlayerId.P1, Side.DYNASTY)))
    apply_intent(table, PlayerId.P1, DestroyProvince(ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)))

    table.validate()
