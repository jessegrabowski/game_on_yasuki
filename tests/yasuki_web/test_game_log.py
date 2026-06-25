from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    Event,
    BoardPos,
    BATTLEFIELD,
    ZoneKey,
    ZoneRole,
    DeckKey,
    MoveCard,
    SetCardPos,
    Bow,
    Flip,
    Draw,
    Shuffle,
    SetHonor,
    SpawnCard,
    RemoveCard,
)
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_web.game_log import describe_intent

P1 = PlayerId.P1


def _board_card(table, card_id="c1", name="Hida Kisada", face_up=True):
    card = L5RCard(id=card_id, name=name, side=Side.DYNASTY, owner=None, face_up=face_up)
    table.battlefield.add(card)
    table.cards_by_id[card_id] = card
    return card


def _describe(table, intent, cards=()):
    return describe_intent(table, "Ada", intent, Event(seq=1, seat=P1, intent=intent, cards=cards))


def test_set_card_pos_is_not_logged():
    assert _describe(TableState.empty_two_seat(), SetCardPos("c1", 1.0, 2.0), ("c1",)) == []


def test_bow_links_a_public_battlefield_card():
    table = TableState.empty_two_seat()
    _board_card(table)
    assert _describe(table, Bow(("c1",)), ("c1",)) == [
        {"text": "Ada "},
        {"text": "bowed "},
        {"card_id": "c1", "name": "Hida Kisada"},
    ]


def test_a_face_down_card_is_never_named():
    table = TableState.empty_two_seat()
    _board_card(table, face_up=False)
    parts = _describe(table, Bow(("c1",)), ("c1",))
    assert {"text": "a card"} in parts
    assert all("name" not in part for part in parts)


def test_a_revealed_face_down_card_is_named():
    table = TableState.empty_two_seat()
    card = L5RCard(id="c1", name="Hida Kisada", side=Side.DYNASTY, owner=None, face_up=False)
    card.reveal()
    table.battlefield.add(card)
    table.cards_by_id["c1"] = card

    assert {"card_id": "c1", "name": "Hida Kisada"} in _describe(table, Bow(("c1",)), ("c1",))


def test_a_face_up_card_off_the_battlefield_is_not_named():
    # Public by its face flag, but in a private/off-board zone — must still read as "a card".
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=True)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    parts = _describe(table, Bow(("f1",)), ("f1",))
    assert {"text": "a card"} in parts
    assert all("name" not in part for part in parts)


def test_a_face_up_card_in_a_province_is_named():
    # Flipping a province card face up makes its identity public, so the log names it.
    table = TableState.empty_two_seat()
    card = L5RCard(id="d1", name="Gold Mine", side=Side.DYNASTY, owner=P1, face_up=True)
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    assert {"card_id": "d1", "name": "Gold Mine"} in _describe(table, Flip(("d1",)), ("d1",))


def test_move_to_a_public_discard_names_the_card():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Ancestral Armor", side=Side.FATE, owner=P1, face_up=True)
    table.zones[ZoneKey(P1, ZoneRole.FATE_DISCARD)].cards.append(card)
    table.cards_by_id["f1"] = card

    intent = MoveCard("f1", ZoneKey(P1, ZoneRole.FATE_DISCARD))
    assert _describe(table, intent, ("f1",)) == [
        {"text": "Ada "},
        {"text": "moved "},
        {"card_id": "f1", "name": "Ancestral Armor"},
        {"text": " to the fate discard"},
    ]


def test_batch_flag_links_each_card():
    table = TableState.empty_two_seat()
    _board_card(table, "c1", "Kisada")
    _board_card(table, "c2", "Sun Tao")
    assert _describe(table, Bow(("c1", "c2")), ("c1", "c2")) == [
        {"text": "Ada "},
        {"text": "bowed "},
        {"card_id": "c1", "name": "Kisada"},
        {"text": ", "},
        {"card_id": "c2", "name": "Sun Tao"},
    ]


def test_spawn_links_the_new_card():
    table = TableState.empty_two_seat()
    _board_card(table, "tok1", "Token")
    intent = SpawnCard("tok1", "Token", Side.DYNASTY, None, BoardPos(0.0, 0.0))
    assert _describe(table, intent, ("tok1",))[-1] == {"card_id": "tok1", "name": "Token"}


def test_move_to_battlefield_links_card_and_names_destination():
    table = TableState.empty_two_seat()
    _board_card(table)
    intent = MoveCard("c1", BATTLEFIELD, BoardPos(1.0, 1.0))
    assert _describe(table, intent, ("c1",)) == [
        {"text": "Ada "},
        {"text": "moved "},
        {"card_id": "c1", "name": "Hida Kisada"},
        {"text": " to the battlefield"},
    ]


def test_move_off_the_battlefield_names_the_destination():
    # A card that left the battlefield is no longer nameable, and the deck destination is described.
    table = TableState.empty_two_seat()
    intent = MoveCard("f1", DeckKey(P1, Side.FATE))
    assert _describe(table, intent, ("f1",)) == [
        {"text": "Ada "},
        {"text": "moved "},
        {"text": "a card"},
        {"text": " to their fate deck"},
    ]


def test_draw_and_shuffle_phrasing():
    table = TableState.empty_two_seat()
    assert _describe(table, Draw(DeckKey(P1, Side.FATE))) == [
        {"text": "Ada "},
        {"text": "drew a card"},
    ]
    assert _describe(table, Shuffle(DeckKey(P1, Side.DYNASTY), seed=1)) == [
        {"text": "Ada "},
        {"text": "shuffled their dynasty deck"},
    ]


def test_set_honor_phrasing():
    table = TableState.empty_two_seat()
    assert _describe(table, SetHonor(value=20))[-1] == {"text": "set their honor to 20"}
    assert _describe(table, SetHonor(delta=3))[-1] == {"text": "gained 3 honor"}
    assert _describe(table, SetHonor(delta=-2))[-1] == {"text": "lost 2 honor"}


def test_remove_is_unlinked():
    table = TableState.empty_two_seat()
    assert _describe(table, RemoveCard("gone"), ("gone",)) == [
        {"text": "Ada "},
        {"text": "removed a card"},
    ]
