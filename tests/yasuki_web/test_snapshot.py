import re
from pathlib import Path

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.engine.redaction import redact
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_web.snapshot import serialize_snapshot

P1, P2 = PlayerId.P1, PlayerId.P2


def _serialized(table, viewer, token_names=None):
    return serialize_snapshot(redact(table, viewer), token_names)


def test_opponent_hand_card_is_a_back_stub_with_no_identity():
    table = TableState.empty_two_seat("Ada", "Kenji")
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=False)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    hand = _serialized(table, P2)["zones"]["P1:hand"]

    # The stub carries the public owner (whose card it is) but no identity.
    assert hand[0] == {"id": "f1", "side": "FATE", "owner": "P1", "token": False, "hidden": True}
    assert "name" not in hand[0]


def test_owner_sees_their_own_hand_card_in_full():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=False)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    hand = _serialized(table, P1)["zones"]["P1:hand"]

    assert hand[0]["name"] == "Secret" and hand[0]["hidden"] is False


def test_a_visible_card_carries_its_art_swap_payload_to_the_client():
    table = TableState.empty_two_seat()
    swap = {
        "donor_img": "sets/le/ambush.png",
        "era": "2016+",
        "layout": "Personality",
        "keywords": ["Shadowlands"],
        "donor_era": "1995-99",
        "donor_layout": "Strategy",
    }
    card = L5RCard(id="f1", name="Kuni Yori", side=Side.FATE, owner=P1, art_swap=swap)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    assert _serialized(table, P1)["zones"]["P1:hand"][0]["art"] == swap


def test_a_card_without_an_art_swap_omits_the_art_key():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Plain", side=Side.FATE, owner=P1)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    assert "art" not in _serialized(table, P1)["zones"]["P1:hand"][0]


def test_a_visible_card_carries_its_note_and_an_unnoted_one_omits_it():
    table = TableState.empty_two_seat()
    noted = L5RCard(id="f1", name="Doomed", side=Side.FATE, owner=P1, note="dead")
    plain = L5RCard(id="f2", name="Plain", side=Side.FATE, owner=P1)
    hand = table.zones[ZoneKey(P1, ZoneRole.HAND)]
    for card in (noted, plain):
        hand.cards.append(card)
        table.cards_by_id[card.id] = card

    serialized = _serialized(table, P1)["zones"]["P1:hand"]
    assert serialized[0]["note"] == "dead"
    assert "note" not in serialized[1]


def test_battlefield_card_carries_art_and_position():
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="t1",
        name="Token",
        side=Side.DYNASTY,
        owner=None,
        face_up=True,
        image_front=Path("sets/x/token.jpg"),
    )
    table.battlefield.cards.append(card)
    table.positions["t1"] = BoardPos(12.0, 34.0)
    table.cards_by_id["t1"] = card

    placed = _serialized(table, P1)["battlefield"][0]

    assert placed["name"] == "Token"
    assert placed["img"] == "sets/x/token.jpg"
    assert (placed["x"], placed["y"]) == (12.0, 34.0)


def test_double_faced_card_shows_the_active_face_and_flip_link():
    table = TableState.empty_two_seat()
    back = L5RCard(
        id="sh__back", name="Defiled", side=Side.STRONGHOLD, image_front=Path("sets/x/b.jpg")
    )
    card = L5RCard(
        id="sh",
        name="Stronghold",
        side=Side.STRONGHOLD,
        owner=None,
        face_up=True,
        image_front=Path("sets/x/a.jpg"),
        back_card_id="sh__back",
        back=back,
        showing_back=True,
    )
    table.battlefield.cards.append(card)
    table.positions["sh"] = BoardPos(0.0, 0.0)
    table.cards_by_id["sh"] = card

    placed = _serialized(table, P1)["battlefield"][0]

    assert placed["name"] == "Defiled"  # the presented (back) face
    assert placed["img"] == "sets/x/b.jpg"
    assert placed["back_card_id"] == "sh__back"
    assert placed["showing_back"] is True


def test_link_only_card_shows_the_front_but_still_signals_the_flip():
    # back_card_id set without a resolved back: the front art is sent, but the flip signals let the
    # client fetch and show the other face by id.
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="sh",
        name="Front",
        side=Side.STRONGHOLD,
        face_up=True,
        image_front=Path("sets/x/a.jpg"),
        back_card_id="sh__back",
        showing_back=True,
    )
    table.battlefield.cards.append(card)
    table.positions["sh"] = BoardPos(0.0, 0.0)
    table.cards_by_id["sh"] = card

    placed = _serialized(table, P1)["battlefield"][0]

    assert placed["name"] == "Front"  # no nested back, so the front art is sent
    assert placed["back_card_id"] == "sh__back"
    assert placed["showing_back"] is True


def test_single_faced_card_omits_the_flip_keys():
    table = TableState.empty_two_seat()
    card = L5RCard(id="t1", name="Token", side=Side.DYNASTY, face_up=True)
    table.battlefield.cards.append(card)
    table.positions["t1"] = BoardPos(0.0, 0.0)
    table.cards_by_id["t1"] = card

    placed = _serialized(table, P1)["battlefield"][0]

    assert "back_card_id" not in placed and "showing_back" not in placed


def test_token_card_is_flagged_in_the_snapshot():
    table = TableState.empty_two_seat()
    token = L5RCard(
        id="tok1", name="Bushi", side=Side.DYNASTY, owner=None, face_up=True, is_token=True
    )
    real = L5RCard(id="c1", name="Hida", side=Side.DYNASTY, owner=None, face_up=True)
    for card in (token, real):
        table.battlefield.cards.append(card)
        table.positions[card.id] = BoardPos(0.0, 0.0)
        table.cards_by_id[card.id] = card

    placed = {c["id"]: c for c in _serialized(table, P1)["battlefield"]}

    assert placed["tok1"]["token"] is True
    assert placed["c1"]["token"] is False  # a real card is never a token


def test_deck_reports_count_only_when_face_down():
    table = TableState.empty_two_seat()
    deck = table.decks[DeckKey(P1, Side.FATE)]
    for i in range(3):
        card = L5RCard(id=f"f{i}", name=f"f{i}", side=Side.FATE, owner=P1, face_up=False)
        deck.cards.append(card)
        table.cards_by_id[card.id] = card

    view = _serialized(table, P2)["decks"]["P1:fate"]

    assert view == {"count": 3, "top": None}


def test_seats_are_public():
    table = TableState.empty_two_seat("Ada", "Kenji")
    table.seats[P1].honor = 14
    table.seats[P2].ready = True

    seats = _serialized(table, P2)["seats"]

    assert seats["P1"] == {
        "name": "Ada",
        "honor": 14,
        "ready": False,
        "connected": False,
        "avatar": None,
    }
    assert seats["P2"]["ready"] is True


def test_seat_avatar_is_public():
    table = TableState.empty_two_seat("Ada", "Kenji")
    spec = {
        "card_id": "doji",
        "image_path": "sets/x/doji.jpg",
        "crop": {"left": 0.1, "top": 0.1, "right": 0.4, "bottom": 0.4},
    }
    table.seats[P1].avatar = spec

    assert _serialized(table, P2)["seats"]["P1"]["avatar"] == spec


def test_a_plain_visible_card_carries_shown_and_peeked_false():
    table = TableState.empty_two_seat()
    card = L5RCard(id="t1", name="Token", side=Side.DYNASTY, owner=None, face_up=True)
    table.battlefield.cards.append(card)
    table.positions["t1"] = BoardPos(0.0, 0.0)
    table.cards_by_id["t1"] = card

    placed = _serialized(table, P1)["battlefield"][0]

    assert placed["shown"] is False and placed["peeked"] is False


def test_shown_hand_card_is_flagged_shown_for_both_seats():
    table = TableState.empty_two_seat()
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=P1, face_up=True, shown=True)
    table.zones[ZoneKey(P1, ZoneRole.HAND)].cards.append(card)
    table.cards_by_id["f1"] = card

    for viewer in (P1, P2):
        view = _serialized(table, viewer)["zones"]["P1:hand"][0]
        assert view["hidden"] is False and view["shown"] is True and view["peeked"] is False


def test_shown_face_down_card_is_flagged_only_for_the_opponent():
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="d1", name="Gold Mine", side=Side.DYNASTY, owner=P1, face_up=False, shown=True
    )
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    opp = _serialized(table, P2)["zones"]["P1:province:0"][0]
    assert opp["hidden"] is False and opp["shown"] is True and opp["peeked"] is False

    owner = _serialized(table, P1)["zones"]["P1:province:0"][0]
    assert owner["hidden"] is True  # the owner still sees a back, with no shown/peeked keys
    assert "shown" not in owner and "peeked" not in owner


def test_peeked_card_is_flagged_peeked_for_the_peeker_only():
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="d1",
        name="Gold Mine",
        side=Side.DYNASTY,
        owner=P1,
        face_up=False,
        peekers=frozenset({P2}),
    )
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[card])
    table.cards_by_id["d1"] = card

    peeker = _serialized(table, P2)["zones"]["P1:province:0"][0]
    assert peeker["hidden"] is False and peeker["peeked"] is True and peeker["shown"] is False

    owner = _serialized(table, P1)["zones"]["P1:province:0"][0]
    assert owner["hidden"] is True  # the owner does not see the peeker's peek


def test_province_key_serializes_with_its_index():
    table = TableState.empty_two_seat()
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 2)] = ProvinceZone(owner=P1)

    assert "P1:province:2" in _serialized(table, P1)["zones"]


def test_card_serializes_creates_for_the_menu():
    table = TableState.empty_two_seat()
    card = L5RCard(
        id="c1",
        name="Curse of the Jackal",
        side=Side.FATE,
        owner=None,
        face_up=True,
        creates=("jackal_pack",),
    )
    table.battlefield.cards.append(card)
    table.positions["c1"] = BoardPos(0.0, 0.0)
    table.cards_by_id["c1"] = card

    serialized = _serialized(table, P1, {"jackal_pack": "Jackal Pack"})["battlefield"][0]
    assert serialized["creates"] == [{"id": "jackal_pack", "name": "Jackal Pack"}]
    # Without the name map (or for a card that creates nothing) the key is omitted.
    assert "creates" not in _serialized(table, P1)["battlefield"][0]


def test_realms_merge_in_province_serializes_creates_but_concealed_face_down():
    # The Realms Merge is an Event that resolves from a province, creating a Zombie or an Oni Hatchling
    # — a creator that never reaches the battlefield, so its Create menu lives in the province.
    table = TableState.empty_two_seat()
    names = {"oni_hatchling": "Oni Hatchling", "zombie": "Zombie"}
    revealed = L5RCard(
        id="c1",
        name="The Realms Merge",
        side=Side.DYNASTY,
        owner=P1,
        face_up=True,
        creates=("oni_hatchling", "zombie"),
    )
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1, cards=[revealed])
    table.cards_by_id["c1"] = revealed
    serialized = _serialized(table, P1, names)["zones"]["P1:province:0"][0]
    assert serialized["creates"] == [
        {"id": "oni_hatchling", "name": "Oni Hatchling"},
        {"id": "zombie", "name": "Zombie"},
    ]

    # A face-down province card is a HiddenCard stub to the opponent, so its creations never leak.
    hidden = L5RCard(
        id="c2",
        name="The Realms Merge",
        side=Side.DYNASTY,
        owner=P1,
        face_up=False,
        creates=("oni_hatchling", "zombie"),
    )
    table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 1)] = ProvinceZone(owner=P1, cards=[hidden])
    table.cards_by_id["c2"] = hidden
    opp = _serialized(table, P2, names)["zones"]["P1:province:1"][0]
    assert "creates" not in opp


def test_card_fields_covers_every_serialized_key():
    # The client's CARD_FIELDS (board.js) must list every key _card emits, or a newly serialized field
    # would silently never re-patch its card on the board. Anchor the JS list to the real serializer.
    table = TableState.empty_two_seat()
    back = L5RCard(id="c1__back", name="Back", side=Side.DYNASTY, image_front=Path("sets/x/b.jpg"))
    card = L5RCard(
        id="c1",
        name="Full",
        side=Side.DYNASTY,
        owner=None,
        face_up=True,
        image_front=Path("sets/x/a.jpg"),
        art_swap={"donor_img": "d.png", "era": "x", "layout": "y", "keywords": []},
        note="dead",
        back_card_id="c1__back",
        back=back,
        showing_back=False,
        creates=("tok1",),
    )
    table.battlefield.cards.append(card)
    table.positions["c1"] = BoardPos(1.0, 2.0)
    table.cards_by_id["c1"] = card

    serialized = set(_serialized(table, P1, {"tok1": "Token One"})["battlefield"][0].keys())
    # Self-check: the fixture must exercise every conditional key, or the guard below is hollow.
    assert {"back_card_id", "showing_back", "art", "note", "creates", "x", "y"} <= serialized

    board_js = Path(__file__).resolve().parents[2] / "src/yasuki_web/static/site/board.js"
    match = re.search(r"CARD_FIELDS = \[(.*?)\]", board_js.read_text(), re.DOTALL)
    assert match, "CARD_FIELDS not found in board.js"
    card_fields = set(re.findall(r"'([^']+)'", match.group(1)))

    missing = serialized - {"id"} - card_fields
    assert not missing, f"board.js CARD_FIELDS is missing serialized keys: {sorted(missing)}"
