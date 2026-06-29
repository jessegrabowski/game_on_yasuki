from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, BoardPos, BATTLEFIELD, ZoneKey, ZoneRole, DeckKey
from yasuki_core.engine.intents import (
    Event,
    MoveCard,
    SetCardPos,
    Bow,
    Flip,
    Show,
    Unshow,
    Peek,
    Unpeek,
    Draw,
    Shuffle,
    SetHonor,
    SpawnCard,
    RemoveCard,
    SearchDeck,
    MoveDeckTop,
    ReorderPile,
    SetNote,
    GiveControl,
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


def test_setting_a_note_is_not_logged():
    # A note is a private annotation; surfacing it would leak the text and clutter the log.
    assert _describe(TableState.empty_two_seat(), SetNote("c1", "dead"), ("c1",)) == []


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


def test_showing_a_fate_card_in_hand_names_it():
    # A hand card the owner already reads, shown to the opponent, is public to all — so it is named.
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=True, shown=True)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    assert _describe(table, Show("f1"), ("f1",)) == [
        {"text": "Ada "},
        {"text": "shows "},
        {"card_id": "f1", "name": "Secret"},
    ]


def test_showing_a_face_down_dynasty_card_stays_generic():
    # The owner still sees a back, so the card is not public to all; naming it would leak it.
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="d1", name="Gold Mine", side=Side.DYNASTY, owner=P1, face_up=False, shown=True
    )
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    parts = _describe(table, Show("d1"), ("d1",))
    assert parts == [{"text": "Ada "}, {"text": "shows a dynasty card"}]
    assert all("name" not in part for part in parts)


def test_unshow_is_generic():
    table = TableState.empty_two_seat()
    card = L5RCard(id="d1", name="Gold Mine", side=Side.DYNASTY, owner=P1, face_up=False)
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    assert _describe(table, Unshow("d1"), ("d1",)) == [
        {"text": "Ada "},
        {"text": "stops showing a dynasty card"},
    ]


def test_peek_is_always_generic():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=False)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    parts = _describe(table, Peek("f1"), ("f1",))
    assert parts == [{"text": "Ada "}, {"text": "peeks at a fate card"}]
    assert all("name" not in part for part in parts)


def test_unpeek_is_generic():
    table = TableState.empty_two_seat()
    card = L5RCard(id="d1", name="Gold Mine", side=Side.DYNASTY, owner=P1, face_up=False)
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    assert _describe(table, Unpeek("d1"), ("d1",)) == [
        {"text": "Ada "},
        {"text": "stops peeking at a dynasty card"},
    ]


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


def test_give_control_names_the_battlefield_card():
    table = TableState.empty_two_seat()
    _board_card(table, "c1", "Hida Kisada")
    segments = _describe(table, GiveControl("c1"), ("c1",))
    assert segments[1] == {"text": "gave control of "}
    assert segments[-1] == {"card_id": "c1", "name": "Hida Kisada"}


def test_spawn_links_the_new_card():
    table = TableState.empty_two_seat()
    _board_card(table, "tok1", "Token")
    intent = SpawnCard(
        card_id="tok1",
        card=L5RCard(id="src", name="Token", side=Side.DYNASTY),
        position=BoardPos(0.0, 0.0),
    )
    assert _describe(table, intent, ("tok1",))[-1] == {"card_id": "tok1", "name": "Token"}


def test_duplicate_links_the_new_card():
    table = TableState.empty_two_seat()
    _board_card(table, "tok1", "Hida Kisada")
    intent = SpawnCard(card_id="tok1", source_card_id="orig", position=BoardPos(0.0, 0.0))
    segments = _describe(table, intent, ("tok1",))
    assert {"text": "duplicated "} in segments
    assert segments[-1] == {"card_id": "tok1", "name": "Hida Kisada"}


def test_create_token_links_the_new_card():
    table = TableState.empty_two_seat()
    _board_card(table, "tok1", "Jackal Pack")
    intent = SpawnCard(card_id="tok1", token_id="jackal_pack", position=BoardPos(0.0, 0.0))
    segments = _describe(table, intent, ("tok1",))
    assert {"text": "created "} in segments
    assert segments[-1] == {"card_id": "tok1", "name": "Jackal Pack"}


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


def test_move_to_a_deck_top_describes_the_destination():
    # A card moved onto a deck reads as "put ... on the top of their <side> deck"; off the
    # battlefield it is no longer nameable, so it reads as "a card".
    table = TableState.empty_two_seat()
    intent = MoveCard("f1", DeckKey(P1, Side.FATE))
    assert _describe(table, intent, ("f1",)) == [
        {"text": "Ada "},
        {"text": "put "},
        {"text": "a card"},
        {"text": " on the top of their fate deck"},
    ]


def test_move_to_a_deck_bottom_says_bottom():
    table = TableState.empty_two_seat()
    intent = MoveCard("f1", DeckKey(P1, Side.DYNASTY), to_bottom=True)
    assert _describe(table, intent, ("f1",))[-1] == {"text": " on the bottom of their dynasty deck"}


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


def test_search_whole_deck_phrasing():
    table = TableState.empty_two_seat()
    assert _describe(table, SearchDeck(DeckKey(P1, Side.FATE))) == [
        {"text": "Ada "},
        {"text": "searched their fate deck"},
    ]


def test_search_top_n_phrasing():
    table = TableState.empty_two_seat()
    assert _describe(table, SearchDeck(DeckKey(P1, Side.DYNASTY), limit=3)) == [
        {"text": "Ada "},
        {"text": "searched the top 3 cards of their dynasty deck"},
    ]


def test_reorder_pile_is_logged_without_revealing_the_card_or_order():
    table = TableState.empty_two_seat()
    assert _describe(table, ReorderPile(DeckKey(P1, Side.FATE), "c1", 0)) == [
        {"text": "Ada "},
        {"text": "reordered their fate deck"},
    ]
    assert _describe(table, ReorderPile(ZoneKey(P1, ZoneRole.DYNASTY_DISCARD), "c1", 2)) == [
        {"text": "Ada "},
        {"text": "reordered their dynasty discard"},
    ]


def test_move_deck_top_to_battlefield_is_described_as_a_move():
    table = TableState.empty_two_seat()
    _board_card(table, "c1", "Token", face_up=True)
    intent = MoveDeckTop(DeckKey(P1, Side.DYNASTY), BATTLEFIELD, BoardPos(0.0, 0.0))
    assert _describe(table, intent, ("c1",)) == [
        {"text": "Ada "},
        {"text": "moved "},
        {"card_id": "c1", "name": "Token"},
        {"text": " to the battlefield"},
    ]
