import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos, BATTLEFIELD
from yasuki_core.engine.intents import (
    MoveCard,
    SetCardPos,
    SetCardPositions,
    ReorderHand,
    ReorderPile,
    SetNote,
    AdjustCounter,
    GiveControl,
    Attach,
    Detach,
    Bow,
    Unbow,
    Flip,
    FlipFace,
    Invert,
    Show,
    Unshow,
    Peek,
    Unpeek,
    Draw,
    Shuffle,
    FlipCoin,
    RollDice,
    coin_flip_outcome,
    dice_roll_outcome,
    FlipDeckTop,
    SearchDeck,
    MoveDeckTop,
    Raise,
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
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyPersonality
from yasuki_core.game_pieces.fate import FateCard


def _fate(card_id: str, owner: PlayerId = PlayerId.P1) -> FateCard:
    return FateCard(id=card_id, name=card_id, side=Side.FATE, owner=owner)


def _dynasty(card_id: str, owner: PlayerId = PlayerId.P1) -> DynastyCard:
    return DynastyCard(id=card_id, name=card_id, side=Side.DYNASTY, owner=owner)


def _on_battlefield(table: TableState, card: L5RCard, pos: BoardPos = BoardPos(0.0, 0.0)) -> None:
    table.cards_by_id[card.id] = card
    table.battlefield.add(card)
    table.positions[card.id] = pos


def test_move_card_battlefield_to_hand_lands_upright_and_face_up():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)
    card.turn_face_up()
    card.bow()
    card.invert()

    events = apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert table.seq == 1
    assert len(events) == 1 and events[0].seq == 1
    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards
    assert card not in table.battlefield.cards
    assert "f1" not in table.positions
    # The owner reads their own hand: a card enters it face up, unbowed, and uninverted, like a draw.
    assert card.face_up is True
    assert card.bowed is False
    assert card.inverted is False


def test_move_card_within_the_same_hand_is_a_no_op():
    table = TableState.empty_two_seat()
    hand = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    card = _fate("f1")
    table.cards_by_id["f1"] = card
    table.zones[hand].add(card)

    events = apply_intent(table, PlayerId.P1, MoveCard("f1", hand))

    # Re-arranging within the hand changes nothing and must not produce a loggable event.
    assert events == []
    assert table.seq == 0
    assert table.zones[hand].cards == [card]


def _stock_hand(table, *card_ids):
    hand = ZoneKey(PlayerId.P1, ZoneRole.HAND)
    for card_id in card_ids:
        card = _fate(card_id)
        table.cards_by_id[card_id] = card
        table.zones[hand].add(card)
    return hand


def test_reorder_hand_moves_a_card_to_a_new_slot():
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a", "b", "c")

    events = apply_intent(table, PlayerId.P1, ReorderHand("c", 0))

    assert [card.id for card in table.zones[hand].cards] == ["c", "a", "b"]
    assert table.seq == 1 and len(events) == 1


def test_reorder_hand_clamps_an_out_of_range_index():
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a", "b", "c")

    apply_intent(table, PlayerId.P1, ReorderHand("a", 99))

    assert [card.id for card in table.zones[hand].cards] == ["b", "c", "a"]


def test_reorder_hand_to_the_same_slot_is_a_no_op():
    table = TableState.empty_two_seat()
    _stock_hand(table, "a", "b", "c")

    events = apply_intent(table, PlayerId.P1, ReorderHand("b", 1))

    assert events == [] and table.seq == 0


def test_reorder_hand_ignores_a_card_not_in_the_hand():
    table = TableState.empty_two_seat()
    _stock_hand(table, "a", "b")

    events = apply_intent(table, PlayerId.P1, ReorderHand("ghost", 0))

    assert events == [] and table.seq == 0


def test_reorder_hand_cannot_touch_the_opponents_hand():
    table = TableState.empty_two_seat()
    card = _fate("theirs", owner=PlayerId.P2)
    table.cards_by_id["theirs"] = card
    table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].add(card)

    events = apply_intent(table, PlayerId.P1, ReorderHand("theirs", 0))

    assert events == [] and table.seq == 0
    assert table.zones[ZoneKey(PlayerId.P2, ZoneRole.HAND)].cards == [card]


# The owner sees a pile top-first; the engine list keeps the top last, so these helpers translate.
def _stock_deck(table, side, *top_first_ids):
    deck_key = DeckKey(PlayerId.P1, side)
    cards = []
    for card_id in top_first_ids:
        card = _fate(card_id)
        table.cards_by_id[card_id] = card
        cards.append(card)
    table.decks[deck_key].cards[:] = list(reversed(cards))
    return deck_key


def _top_first(cards):
    return [card.id for card in reversed(cards)]


def test_reorder_pile_moves_a_deck_card_to_the_top():
    table = TableState.empty_two_seat()
    deck = _stock_deck(table, Side.FATE, "a", "b", "c")  # owner sees a (top), b, c

    events = apply_intent(table, PlayerId.P1, ReorderPile(deck, "c", 0))

    assert _top_first(table.decks[deck].cards) == ["c", "a", "b"]
    assert table.seq == 1 and len(events) == 1


def test_reorder_pile_reorders_a_discard_in_the_owners_view():
    table = TableState.empty_two_seat()
    pile = ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)
    cards = [_fate("a"), _fate("b"), _fate("c")]
    for card in cards:
        table.cards_by_id[card.id] = card
    table.zones[pile].cards[:] = list(reversed(cards))  # owner sees a (top), b, c

    apply_intent(table, PlayerId.P1, ReorderPile(pile, "a", 2))

    assert _top_first(table.zones[pile].cards) == ["b", "c", "a"]


def test_reorder_pile_clamps_and_no_ops_at_the_same_slot():
    table = TableState.empty_two_seat()
    deck = _stock_deck(table, Side.FATE, "a", "b", "c")

    assert apply_intent(table, PlayerId.P1, ReorderPile(deck, "b", 1)) == []  # b already at slot 1
    apply_intent(table, PlayerId.P1, ReorderPile(deck, "a", 99))  # clamps to the bottom
    assert _top_first(table.decks[deck].cards) == ["b", "c", "a"]


def test_reorder_pile_cannot_touch_an_opponents_deck():
    table = TableState.empty_two_seat()
    deck = DeckKey(PlayerId.P2, Side.FATE)
    cards = [_fate("x", owner=PlayerId.P2), _fate("y", owner=PlayerId.P2)]
    for card in cards:
        table.cards_by_id[card.id] = card
    table.decks[deck].cards[:] = cards

    events = apply_intent(table, PlayerId.P1, ReorderPile(deck, "x", 0))

    assert events == [] and table.seq == 0


def test_set_note_sets_strips_and_clears():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, SetNote("f1", "  dead  "))
    assert card.note == "dead"  # surrounding whitespace trimmed

    events = apply_intent(table, PlayerId.P1, SetNote("f1", ""))  # an empty note removes it
    assert card.note is None and len(events) == 1


def test_set_note_is_rejected_on_a_face_down_card():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.turn_face_down()
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, SetNote("f1", "secret"))

    assert events == [] and card.note is None


def test_set_note_to_the_same_value_is_a_no_op():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.set_note("dead")
    _on_battlefield(table, card)

    assert apply_intent(table, PlayerId.P1, SetNote("f1", "dead")) == []


def test_a_note_rides_a_card_into_the_discard_but_clears_in_a_deck():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.set_note("dead")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)))
    assert card.note == "dead"  # the discard is public — the marker stays

    apply_intent(table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P1, Side.FATE)))
    assert card.note is None  # shuffled back into the deck — the marker is gone


def test_adjust_counter_grants_and_removes_on_a_face_up_card():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, 2))
    assert card.counters == {"wealth": 2} and len(events) == 1

    apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, -2))
    assert card.counters == {}


def test_adjust_counter_may_token_an_opponents_card():
    # Effects legitimately token another player's cards (Takeru Sensei), so there is no owner gate.
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, 1))

    assert card.counters == {"wealth": 1} and len(events) == 1


def test_adjust_counter_is_rejected_on_a_face_down_card():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.turn_face_down()
    _on_battlefield(table, card)

    assert apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, 1)) == []
    assert card.counters == {}


def test_adjust_counter_that_changes_nothing_is_a_no_op():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    # Removing from an empty tally floors at zero, so nothing changes and no event is emitted.
    assert apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, -3)) == []
    assert apply_intent(table, PlayerId.P1, AdjustCounter("f1", WEALTH, 0)) == []


def test_give_control_hands_a_battlefield_card_to_the_opponent():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, GiveControl("f1"))

    assert card.owner == PlayerId.P2 and len(events) == 1


def test_give_control_is_rejected_on_the_opponents_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, GiveControl("f1"))

    assert events == [] and card.owner == PlayerId.P2


def test_give_control_is_rejected_on_a_face_down_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    card.turn_face_down()
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, GiveControl("f1"))

    assert events == [] and card.owner == PlayerId.P1


def test_give_control_is_rejected_on_a_public_card():
    # A public (owner-less) card has no controller to transfer; only a card you own may be given away.
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=None)
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, GiveControl("f1"))

    assert events == [] and card.owner is None


def test_give_control_is_rejected_off_the_battlefield():
    # Reassigning a card held in an owned zone would break the zone/owner invariant, so it's refused.
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a")
    card = table.zones[hand].cards[0]

    events = apply_intent(table, PlayerId.P1, GiveControl(card.id))

    assert events == [] and card.owner == PlayerId.P1


def test_move_card_into_the_hand_lands_at_the_given_slot():
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a", "b", "c")
    card = _fate("new")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("new", hand, index=1))

    assert [held.id for held in table.zones[hand].cards] == ["a", "new", "b", "c"]


def test_move_card_into_the_hand_without_an_index_appends():
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a", "b")
    card = _fate("new")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("new", hand))

    assert [held.id for held in table.zones[hand].cards] == ["a", "b", "new"]


def test_move_card_into_the_hand_clamps_an_out_of_range_index():
    table = TableState.empty_two_seat()
    hand = _stock_hand(table, "a", "b")
    card = _fate("new")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("new", hand, index=99))

    assert [held.id for held in table.zones[hand].cards] == ["a", "b", "new"]


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


def test_play_face_down_lays_the_card_down_and_peeks_it_back_to_its_owner():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.turn_face_up()
    table.cards_by_id["f1"] = card
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    events = apply_intent(
        table, PlayerId.P1, MoveCard("f1", BATTLEFIELD, BoardPos(3.0, 4.0), face_down=True)
    )

    assert card in table.battlefield.cards
    assert card.face_up is False
    # The owner peeks their own focused card, so they still read it while the opponent sees a back.
    assert PlayerId.P1 in card.peekers
    assert PlayerId.P2 not in card.peekers
    # The resolved event mirrors the face-down directive, so a replay reproduces it.
    assert events[0].intent.face_down is True


def test_normal_play_from_hand_stays_face_up_and_unpeeked():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.turn_face_up()
    table.cards_by_id["f1"] = card
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", BATTLEFIELD, BoardPos(3.0, 4.0)))

    assert card.face_up is True
    assert not card.peekers


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
    card.set_note("dead")
    card.show()
    card.add_peeker(PlayerId.P1)
    card.add_peeker(PlayerId.P2)
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P1, Side.FATE)))

    assert card in table.decks[DeckKey(PlayerId.P1, Side.FATE)].cards
    # A card shuffled back into the library is scrubbed to a plain face-down card no one can read.
    assert card.face_up is False
    assert card.bowed is False
    assert card.inverted is False
    assert card.note is None
    assert card.shown is False
    assert card.peekers == frozenset()


def test_move_card_to_deck_top_by_default():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    deck.cards.extend([_fate("a"), _fate("b")])
    card = _fate("f1")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P1, Side.FATE)))

    assert deck.cards[-1] is card


def test_move_card_to_deck_bottom_slides_under():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    deck.cards.extend([_fate("a"), _fate("b")])
    card = _fate("f1")
    _on_battlefield(table, card)

    events = apply_intent(
        table, PlayerId.P1, MoveCard("f1", DeckKey(PlayerId.P1, Side.FATE), to_bottom=True)
    )

    assert deck.cards[0] is card
    assert events[0].intent.to_bottom is True


def test_flip_deck_top_reveals_the_top_card_in_place():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    under, top = _fate("a"), _fate("b")
    top.turn_face_down()
    deck.cards.extend([under, top])

    events = apply_intent(table, PlayerId.P1, FlipDeckTop(DeckKey(PlayerId.P1, Side.FATE)))

    assert top.face_up is True
    assert deck.cards[-1] is top
    assert events[0].cards == ("b",)
    assert table.seq == 1


def test_flip_deck_top_toggles_back_to_face_down():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    card = _fate("b")
    card.turn_face_up()
    deck.cards.append(card)

    apply_intent(table, PlayerId.P1, FlipDeckTop(DeckKey(PlayerId.P1, Side.FATE)))

    assert card.face_up is False


def test_flip_deck_top_on_empty_deck_is_a_no_op():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, FlipDeckTop(DeckKey(PlayerId.P1, Side.FATE)))
    assert events == []
    assert table.seq == 0


def test_flip_deck_top_rejects_opponents_deck():
    table = TableState.empty_two_seat()
    table.decks[DeckKey(PlayerId.P2, Side.FATE)].cards.append(_fate("b", owner=PlayerId.P2))
    events = apply_intent(table, PlayerId.P1, FlipDeckTop(DeckKey(PlayerId.P2, Side.FATE)))
    assert events == []
    assert table.seq == 0


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


def test_move_card_into_a_discard_turns_it_face_up():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.turn_face_down()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)))

    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards
    # A discard pile is always public, so the card lands face up regardless of how it arrived.
    assert card.face_up is True


def test_move_card_into_dynasty_discard_turns_it_face_up():
    table = TableState.empty_two_seat()
    card = _dynasty("d1")
    card.turn_face_down()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("d1", ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)))

    assert table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards[0].face_up is True


def test_move_card_into_a_discard_unbows():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    card.bow()
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, MoveCard("f1", ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)))

    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards
    assert card.bowed is False


def test_move_deck_top_to_battlefield_pops_the_top_card():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(PlayerId.P1, Side.FATE)]
    under, top = _fate("under"), _fate("top")
    for card in (under, top):
        table.cards_by_id[card.id] = card
    deck.cards.extend([under, top])

    events = apply_intent(
        table,
        PlayerId.P1,
        MoveDeckTop(DeckKey(PlayerId.P1, Side.FATE), BATTLEFIELD, BoardPos(2.0, 3.0)),
    )

    assert top in table.battlefield.cards
    assert table.positions["top"] == BoardPos(2.0, 3.0)
    assert deck.cards == [under]
    assert events[0].cards == ("top",)


def test_move_deck_top_into_a_zone_routes_like_a_move():
    table = TableState.empty_two_seat()
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=PlayerId.P1)
    deck = table.decks[DeckKey(PlayerId.P1, Side.DYNASTY)]
    card = _dynasty("d1")
    table.cards_by_id["d1"] = card
    deck.cards.append(card)

    apply_intent(
        table,
        PlayerId.P1,
        MoveDeckTop(DeckKey(PlayerId.P1, Side.DYNASTY), ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)),
    )

    assert card in table.zones[ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)].cards
    assert deck.cards == []


def test_move_deck_top_rejects_opponents_deck():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P2)
    table.cards_by_id["f1"] = card
    table.decks[DeckKey(PlayerId.P2, Side.FATE)].cards.append(card)

    events = apply_intent(
        table, PlayerId.P1, MoveDeckTop(DeckKey(PlayerId.P2, Side.FATE), BATTLEFIELD)
    )

    assert events == []
    assert card in table.decks[DeckKey(PlayerId.P2, Side.FATE)].cards


def test_move_deck_top_on_empty_deck_is_a_no_op():
    table = TableState.empty_two_seat()
    events = apply_intent(
        table, PlayerId.P1, MoveDeckTop(DeckKey(PlayerId.P1, Side.FATE), BATTLEFIELD)
    )
    assert events == [] and table.seq == 0


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


def test_set_card_positions_moves_a_group_in_one_event():
    table = TableState.empty_two_seat()
    _on_battlefield(table, _fate("f1"), BoardPos(0.0, 0.0))
    _on_battlefield(table, _fate("f2"), BoardPos(0.0, 0.0))

    events = apply_intent(
        table, PlayerId.P1, SetCardPositions((("f1", 5.0, 6.0), ("f2", 7.0, 8.0)))
    )

    assert table.positions["f1"] == BoardPos(5.0, 6.0)
    assert table.positions["f2"] == BoardPos(7.0, 8.0)
    assert table.seq == 1
    assert len(events) == 1
    assert set(events[0].cards) == {"f1", "f2"}


def test_set_card_positions_skips_unowned_and_unchanged_members():
    table = TableState.empty_two_seat()
    _on_battlefield(table, _fate("mine"), BoardPos(0.0, 0.0))
    _on_battlefield(table, _fate("stay"), BoardPos(3.0, 3.0))
    _on_battlefield(table, _fate("theirs", owner=PlayerId.P2), BoardPos(1.0, 1.0))

    events = apply_intent(
        table,
        PlayerId.P1,
        SetCardPositions((("mine", 9.0, 9.0), ("stay", 3.0, 3.0), ("theirs", 4.0, 4.0))),
    )

    assert table.positions["mine"] == BoardPos(9.0, 9.0)
    assert table.positions["theirs"] == BoardPos(1.0, 1.0)
    assert events[0].cards == ("mine",)


def test_set_card_positions_no_op_when_nothing_changes():
    table = TableState.empty_two_seat()
    _on_battlefield(table, _fate("f1"), BoardPos(2.0, 2.0))

    events = apply_intent(table, PlayerId.P1, SetCardPositions((("f1", 2.0, 2.0),)))

    assert events == []
    assert table.seq == 0


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


def test_flip_clears_a_peek_so_turning_the_card_back_down_yields_a_plain_back():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    card.turn_face_down()
    _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Peek("f1"))
    assert card.peekers == frozenset({PlayerId.P1})

    # Flipping the peeked card face up makes it public and consumes the private peek...
    apply_intent(table, PlayerId.P1, Flip(("f1",)))
    assert card.face_up is True
    assert card.peekers == frozenset()

    # ...so flipping it back down leaves a genuine back, not a card its owner still reads.
    apply_intent(table, PlayerId.P1, Flip(("f1",)))
    assert card.face_up is False
    assert card.peekers == frozenset()


def test_flip_face_toggles_a_double_faced_card():
    table = TableState.empty_two_seat()
    back = L5RCard(id="sh__back", name="Back", side=Side.STRONGHOLD)
    card = L5RCard(id="sh", name="Front", side=Side.STRONGHOLD, back_card_id="sh__back", back=back)
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, FlipFace(("sh",)))
    assert card.showing_back is True
    assert card.active_face is back
    apply_intent(table, PlayerId.P1, FlipFace(("sh",)))
    assert card.showing_back is False
    assert table.seq == 2


def test_flip_face_is_rejected_for_a_single_faced_card():
    table = TableState.empty_two_seat()
    card = _fate("f1")  # no back_card_id
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, FlipFace(("f1",)))

    assert events == []
    assert card.showing_back is False
    assert table.seq == 0


def test_flip_face_toggles_with_only_the_back_link():
    # The common runtime case: the server has the back link but not the resolved back face.
    table = TableState.empty_two_seat()
    card = L5RCard(id="sh", name="Front", side=Side.STRONGHOLD, back_card_id="sh__back")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, FlipFace(("sh",)))

    assert card.showing_back is True
    assert table.seq == 1


def test_invert_toggles_both_directions():
    table = TableState.empty_two_seat()
    card = _fate("f1")
    _on_battlefield(table, card)

    apply_intent(table, PlayerId.P1, Invert(("f1",)))
    assert card.inverted is True
    apply_intent(table, PlayerId.P1, Invert(("f1",)))
    assert card.inverted is False


def test_show_and_unshow_are_owner_gated():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    _on_battlefield(table, card)

    # The opponent cannot show another seat's card.
    assert apply_intent(table, PlayerId.P2, Show("f1")) == []
    assert card.shown is False

    assert apply_intent(table, PlayerId.P1, Show("f1")) != []
    assert card.shown is True
    # Showing an already-shown card is a no-op (no event, seq unchanged).
    assert apply_intent(table, PlayerId.P1, Show("f1")) == []

    assert apply_intent(table, PlayerId.P2, Unshow("f1")) == []
    assert card.shown is True
    assert apply_intent(table, PlayerId.P1, Unshow("f1")) != []
    assert card.shown is False


def test_peek_is_owner_gated_to_your_own_hidden_card():
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    _on_battlefield(table, card)

    # The opponent cannot peek your hidden card — they must wait for you to Show it.
    assert apply_intent(table, PlayerId.P2, Peek("f1")) == []
    assert card.peekers == frozenset()

    # You may privately peek your own; a repeat is a no-op, and unpeek clears you again.
    assert apply_intent(table, PlayerId.P1, Peek("f1")) != []
    assert card.peekers == frozenset({PlayerId.P1})
    assert apply_intent(table, PlayerId.P1, Peek("f1")) == []
    assert apply_intent(table, PlayerId.P1, Unpeek("f1")) != []
    assert card.peekers == frozenset()


def test_unpeek_drops_a_peek_even_after_control_passes_to_the_opponent():
    # Unpeek is not owner-gated: whoever holds a peek may always drop it, even once the card has
    # changed hands — so a stale peek never lingers after a Give control.
    table = TableState.empty_two_seat()
    card = _fate("f1", owner=PlayerId.P1)
    _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Peek("f1"))

    card.set_owner(PlayerId.P2)
    assert apply_intent(table, PlayerId.P1, Unpeek("f1")) != []
    assert card.peekers == frozenset()


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
    # The unplaced sentinel (negative): the client lays it out next to the dynasty deck.
    assert table.positions["d1"] == BoardPos(-1.0, -1.0)
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
    intent = SpawnCard(
        card_id="tok1",
        card=L5RCard(id="src", name="Bushi Token", side=Side.DYNASTY),
        position=BoardPos(5.0, 6.0),
    )

    events = apply_intent(table, PlayerId.P1, intent)

    assert table.seq == 1 and events[0].cards == ("tok1",)
    card = table.cards_by_id["tok1"]
    assert card.owner is None and card.face_up is True
    assert card.is_token is True  # spawned pieces are tokens, the only removable cards
    assert card in table.battlefield.cards
    assert table.positions["tok1"] == BoardPos(5.0, 6.0)
    table.validate()


def test_spawn_card_with_token_id_copies_the_full_template():
    table = TableState.empty_two_seat()
    table.creatable_tokens["ghul"] = DynastyPersonality(
        id="ghul",
        name="Ghul",
        side=Side.DYNASTY,
        force=2,
        chi=2,
        personal_honor=0,
        keywords=("Shadowlands", "Ghul", "Undead"),
    )
    intent = SpawnCard(card_id="spawn-1", token_id="ghul", position=BoardPos(1.0, 2.0))

    events = apply_intent(table, PlayerId.P1, intent)

    card = table.cards_by_id["spawn-1"]
    assert events[0].cards == ("spawn-1",)
    assert card.is_token and card.owner is None and card.face_up is True
    # The spawned token is the full typed template, not a name/image stub.
    assert isinstance(card, DynastyPersonality)
    assert (card.force, card.chi) == (2, 2)
    assert card.keywords == ("Shadowlands", "Ghul", "Undead")
    assert table.positions["spawn-1"] == BoardPos(1.0, 2.0)
    table.validate()


def test_spawn_card_with_unknown_token_id_is_rejected():
    table = TableState.empty_two_seat()
    intent = SpawnCard(card_id="spawn-1", token_id="missing", position=BoardPos(0.0, 0.0))
    assert apply_intent(table, PlayerId.P1, intent) == []
    assert "spawn-1" not in table.cards_by_id


def test_spawn_card_with_source_card_id_duplicates_a_full_in_play_card():
    table = TableState.empty_two_seat()
    source = DynastyPersonality(
        id="hero",
        name="Hero",
        side=Side.DYNASTY,
        force=3,
        chi=2,
        keywords=("Lion",),
        owner=PlayerId.P1,
        face_up=True,
    )
    table.cards_by_id["hero"] = source
    table.battlefield.cards.append(source)
    table.positions["hero"] = BoardPos(0.0, 0.0)
    intent = SpawnCard(card_id="spawn-1", source_card_id="hero", position=BoardPos(5.0, 6.0))

    apply_intent(table, PlayerId.P2, intent)  # a public card is duplicable by either seat

    copy = table.cards_by_id["spawn-1"]
    assert isinstance(copy, DynastyPersonality)
    assert (copy.force, copy.chi) == (3, 2) and copy.keywords == ("Lion",)
    assert copy.is_token and copy.owner is None and copy.id != source.id
    table.validate()


def test_spawn_card_duplicating_a_non_public_source_is_rejected():
    table = TableState.empty_two_seat()
    hidden = DynastyPersonality(
        id="facedown", name="Hidden", side=Side.DYNASTY, owner=PlayerId.P1, face_up=False
    )
    table.cards_by_id["facedown"] = hidden
    table.battlefield.cards.append(hidden)
    table.positions["facedown"] = BoardPos(0.0, 0.0)
    intent = SpawnCard(card_id="spawn-1", source_card_id="facedown", position=BoardPos(1.0, 1.0))
    assert apply_intent(table, PlayerId.P1, intent) == []
    assert "spawn-1" not in table.cards_by_id


def test_spawn_card_rejects_a_duplicate_id():
    table = TableState.empty_two_seat()
    intent = SpawnCard(
        card_id="tok1",
        card=L5RCard(id="src", name="X", side=Side.FATE),
        position=BoardPos(0.0, 0.0),
    )
    apply_intent(table, PlayerId.P1, intent)

    assert apply_intent(table, PlayerId.P1, intent) == []


def test_remove_card_takes_a_public_card_off_the_table():
    table = TableState.empty_two_seat()
    apply_intent(
        table,
        PlayerId.P1,
        SpawnCard(
            card_id="tok1",
            card=L5RCard(id="src", name="X", side=Side.FATE),
            position=BoardPos(0.0, 0.0),
        ),
    )

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


def test_remove_card_rejects_a_real_non_token_card():
    table = TableState.empty_two_seat()
    card = _fate("f1")  # a real card, not a spawned token
    _on_battlefield(table, card)

    assert apply_intent(table, PlayerId.P1, RemoveCard("f1")) == []
    assert "f1" in table.cards_by_id  # a real card is never destroyed outright
    assert table.seq == 0


def test_raise_brings_a_battlefield_card_to_the_top_of_the_stack():
    table = TableState.empty_two_seat()
    bottom, middle, top = _fate("b"), _fate("m"), _fate("t")
    for card in (bottom, middle, top):
        _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, Raise("b"))

    # The raised card moves to the end of the list (rendered last = on top); others keep order.
    assert [c.id for c in table.battlefield.cards] == ["m", "t", "b"]
    assert events[0].cards == ("b",) and table.seq == 1


def test_raise_a_card_already_on_top_is_a_no_op():
    table = TableState.empty_two_seat()
    a, b = _fate("a"), _fate("b")
    _on_battlefield(table, a)
    _on_battlefield(table, b)

    events = apply_intent(table, PlayerId.P1, Raise("b"))  # b is already last

    assert events == [] and table.seq == 0


def test_raise_rejects_opponents_card():
    table = TableState.empty_two_seat()
    mine = _fate("f1")
    theirs = _fate("f2", owner=PlayerId.P2)
    _on_battlefield(table, mine)
    _on_battlefield(table, theirs)

    assert apply_intent(table, PlayerId.P1, Raise("f2")) == []
    assert [c.id for c in table.battlefield.cards] == ["f1", "f2"]  # unchanged


def test_set_card_pos_raises_the_moved_card_to_the_top():
    table = TableState.empty_two_seat()
    a, b = _fate("a"), _fate("b")
    _on_battlefield(table, a, BoardPos(1.0, 1.0))
    _on_battlefield(table, b, BoardPos(2.0, 2.0))

    apply_intent(table, PlayerId.P1, SetCardPos("a", 9.0, 9.0))

    assert [c.id for c in table.battlefield.cards] == ["b", "a"]


def test_moving_a_card_onto_the_battlefield_puts_it_on_top():
    table = TableState.empty_two_seat()
    sitting = _fate("sitting")
    _on_battlefield(table, sitting)
    coming = _fate("coming")
    table.cards_by_id["coming"] = coming
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(coming)

    apply_intent(table, PlayerId.P1, MoveCard("coming", BATTLEFIELD, BoardPos(5.0, 5.0)))

    assert [c.id for c in table.battlefield.cards] == ["sitting", "coming"]


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


def test_attach_records_a_card_to_card_relationship():
    table = TableState.empty_two_seat()
    parent, child = _fate("p"), _fate("c")
    _on_battlefield(table, parent)
    _on_battlefield(table, child)

    events = apply_intent(table, PlayerId.P1, Attach("c", "p"))

    assert table.attachments == {"c": "p"}
    assert table.seq == 1
    assert len(events) == 1 and events[0].cards == ("c",)
    # The child keeps its own board position — the attachment is a relationship, not a move.
    assert table.positions["c"] == BoardPos(0.0, 0.0)
    table.validate()


def test_attach_to_a_province_zone():
    table = TableState.empty_two_seat()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    fort = _dynasty("fort")
    _on_battlefield(table, fort)

    events = apply_intent(table, PlayerId.P1, Attach("fort", province))

    assert table.attachments == {"fort": province}
    assert table.seq == 1
    assert len(events) == 1 and events[0].cards == ("fort",)
    table.validate()


def test_attach_to_the_same_target_is_a_no_op():
    table = TableState.empty_two_seat()
    parent, child = _fate("p"), _fate("c")
    _on_battlefield(table, parent)
    _on_battlefield(table, child)
    apply_intent(table, PlayerId.P1, Attach("c", "p"))

    events = apply_intent(table, PlayerId.P1, Attach("c", "p"))

    assert events == [] and table.seq == 1


def test_attach_rejects_a_self_attach():
    table = TableState.empty_two_seat()
    card = _fate("c")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, Attach("c", "c"))

    assert events == [] and table.attachments == {}


def test_attach_rejects_a_cycle():
    table = TableState.empty_two_seat()
    a, b, c = _fate("a"), _fate("b"), _fate("c")
    for card in (a, b, c):
        _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Attach("a", "b"))
    apply_intent(table, PlayerId.P1, Attach("b", "c"))

    # a→b→c already; hanging c off a would close the loop. The guard must walk the whole chain.
    events = apply_intent(table, PlayerId.P1, Attach("c", "a"))

    assert events == [] and table.attachments == {"a": "b", "b": "c"}


def test_attach_rejects_a_target_not_on_the_battlefield():
    table = TableState.empty_two_seat()
    child = _fate("c")
    _on_battlefield(table, child)
    in_hand = _fate("h")
    table.cards_by_id["h"] = in_hand
    table.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].add(in_hand)

    events = apply_intent(table, PlayerId.P1, Attach("c", "h"))

    assert events == [] and table.attachments == {}


def test_attach_rejects_a_missing_province():
    table = TableState.empty_two_seat()
    child = _fate("c")
    _on_battlefield(table, child)

    events = apply_intent(
        table, PlayerId.P1, Attach("c", ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0))
    )

    assert events == [] and table.attachments == {}


def test_attach_is_owner_gated_on_the_child():
    table = TableState.empty_two_seat()
    parent, child = _fate("p"), _fate("c")
    _on_battlefield(table, parent)
    _on_battlefield(table, child)

    # P2 does not control the child and cannot attach it.
    events = apply_intent(table, PlayerId.P2, Attach("c", "p"))

    assert events == [] and table.attachments == {}


def test_detach_breaks_the_childs_own_link_only():
    table = TableState.empty_two_seat()
    grandparent, parent, child = _fate("g"), _fate("p"), _fate("c")
    for card in (grandparent, parent, child):
        _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Attach("p", "g"))
    apply_intent(table, PlayerId.P1, Attach("c", "p"))

    events = apply_intent(table, PlayerId.P1, Detach("p"))

    # p detaches from g, but c stays hung on p.
    assert table.attachments == {"c": "p"}
    assert len(events) == 1 and events[0].cards == ("p",)
    table.validate()


def test_detach_an_unattached_card_is_a_no_op():
    table = TableState.empty_two_seat()
    card = _fate("c")
    _on_battlefield(table, card)

    events = apply_intent(table, PlayerId.P1, Detach("c"))

    assert events == [] and table.seq == 0


def test_moving_a_child_off_the_battlefield_detaches_it():
    table = TableState.empty_two_seat()
    parent, child = _fate("p"), _fate("c")
    _on_battlefield(table, parent)
    _on_battlefield(table, child)
    apply_intent(table, PlayerId.P1, Attach("c", "p"))

    apply_intent(table, PlayerId.P1, MoveCard("c", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert table.attachments == {}
    table.validate()


def test_moving_a_parent_off_the_battlefield_detaches_its_children():
    table = TableState.empty_two_seat()
    parent, child = _fate("p"), _fate("c")
    _on_battlefield(table, parent)
    _on_battlefield(table, child)
    apply_intent(table, PlayerId.P1, Attach("c", "p"))

    apply_intent(table, PlayerId.P1, MoveCard("p", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert table.attachments == {}
    table.validate()


def test_destroying_a_province_discards_what_hangs_on_it():
    table = TableState.empty_two_seat()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    fort = _dynasty("fort")
    _on_battlefield(table, fort)
    fort.bow()
    apply_intent(table, PlayerId.P1, Attach("fort", province))

    apply_intent(table, PlayerId.P1, DestroyProvince(province))

    # The attached dynasty card follows the province into its owner's dynasty discard, face up and
    # unbowed, no longer on the battlefield or attached.
    dynasty_discard = table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)]
    assert fort in dynasty_discard.cards
    assert fort not in table.battlefield.cards
    assert fort.face_up is True and fort.bowed is False
    assert table.attachments == {}
    table.validate()


def test_destroying_a_province_routes_a_fate_attachment_to_the_fate_discard():
    table = TableState.empty_two_seat()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    spell = _fate("spell")  # a fate-side card riding the province routes by its own side/owner
    _on_battlefield(table, spell)
    apply_intent(table, PlayerId.P1, Attach("spell", province))

    apply_intent(table, PlayerId.P1, DestroyProvince(province))

    assert spell in table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards
    table.validate()


def test_destroying_a_province_detaches_a_side_without_a_discard_in_place():
    # A stronghold-side card has no discard; destroying its province must detach it, not remove it from
    # the board into a pile that rejects its side and leave it floating (a corrupt cards_by_id).
    table = TableState.empty_two_seat()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    keep = L5RCard(id="keep", name="Kyuden", side=Side.STRONGHOLD, owner=PlayerId.P1)
    _on_battlefield(table, keep)
    apply_intent(table, PlayerId.P1, Attach("keep", province))

    apply_intent(table, PlayerId.P1, DestroyProvince(province))

    assert keep in table.battlefield.cards  # stays on the board, just detached
    assert table.attachments == {}
    table.validate()


def test_destroying_a_province_discards_every_attachment_to_its_own_pile():
    table = TableState.empty_two_seat()
    province = ZoneKey(PlayerId.P1, ZoneRole.PROVINCE, 0)
    table.zones[province] = ProvinceZone(owner=PlayerId.P1)
    fort, spell = _dynasty("fort"), _fate("spell")
    _on_battlefield(table, fort)
    _on_battlefield(table, spell)
    apply_intent(table, PlayerId.P1, Attach("fort", province))
    apply_intent(table, PlayerId.P1, Attach("spell", province))

    apply_intent(table, PlayerId.P1, DestroyProvince(province))

    # Every attached card is discarded, each routed by its own side — not just the first.
    assert fort in table.zones[ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert spell in table.zones[ZoneKey(PlayerId.P1, ZoneRole.FATE_DISCARD)].cards
    assert table.attachments == {}
    table.validate()


def test_removing_a_card_detaches_what_hangs_on_it():
    table = TableState.empty_two_seat()
    apply_intent(
        table, PlayerId.P1, SpawnCard("host", "Host", Side.DYNASTY, None, BoardPos(0.0, 0.0))
    )
    apply_intent(
        table, PlayerId.P1, SpawnCard("rider", "Rider", Side.FATE, None, BoardPos(1.0, 1.0))
    )
    apply_intent(table, PlayerId.P1, Attach("rider", "host"))

    apply_intent(table, PlayerId.P1, RemoveCard("host"))

    assert table.attachments == {}
    table.validate()


def test_moving_a_middle_node_off_the_battlefield_clears_both_its_links():
    table = TableState.empty_two_seat()
    grandparent, parent, child = _fate("g"), _fate("p"), _fate("c")
    for card in (grandparent, parent, child):
        _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Attach("p", "g"))
    apply_intent(table, PlayerId.P1, Attach("c", "p"))

    # p has both a parent (g) and a child (c). Moving it off the board clears both — unlike Detach(p),
    # which would break only p→g and leave c→p.
    apply_intent(table, PlayerId.P1, MoveCard("p", ZoneKey(PlayerId.P1, ZoneRole.HAND)))

    assert table.attachments == {}
    table.validate()


def test_re_attaching_to_a_different_parent_updates_and_emits():
    table = TableState.empty_two_seat()
    first, second, child = _fate("p1"), _fate("p2"), _fate("c")
    for card in (first, second, child):
        _on_battlefield(table, card)
    apply_intent(table, PlayerId.P1, Attach("c", "p1"))

    events = apply_intent(table, PlayerId.P1, Attach("c", "p2"))

    assert table.attachments == {"c": "p2"}
    assert table.seq == 2 and len(events) == 1
    table.validate()


def test_flip_coin_is_read_only_and_always_accepted():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P2, FlipCoin(seed=1))
    assert len(events) == 1
    assert events[0].intent == FlipCoin(seed=1)
    assert table.seq == 0  # read-only: the coin changes nothing


def test_roll_dice_is_read_only_and_always_accepted():
    table = TableState.empty_two_seat()
    events = apply_intent(table, PlayerId.P1, RollDice(seed=1, sides=20))
    assert len(events) == 1
    assert events[0].intent == RollDice(seed=1, sides=20)
    assert table.seq == 0


@pytest.mark.parametrize("sides", [1, 0, -3])
def test_roll_dice_rejects_fewer_than_two_sides(sides):
    with pytest.raises(ValueError):
        RollDice(seed=1, sides=sides)


def test_roll_dice_accepts_the_two_sided_minimum():
    assert RollDice(seed=1, sides=2).sides == 2


def test_coin_flip_outcome_is_deterministic_and_covers_both_faces():
    faces = {coin_flip_outcome(seed) for seed in range(20)}
    assert faces == {"Heads", "Tails"}
    assert coin_flip_outcome(7) == coin_flip_outcome(7)


def test_dice_roll_outcome_covers_every_face_and_is_deterministic():
    assert {dice_roll_outcome(seed, 6) for seed in range(50)} == {1, 2, 3, 4, 5, 6}
    assert dice_roll_outcome(7, 6) == dice_roll_outcome(7, 6)
