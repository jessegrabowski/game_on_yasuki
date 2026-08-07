import asyncio

import pytest
from numpy.random import SeedSequence

from yasuki_web import websocket as ws_module
from yasuki_web.websocket import GameRoom
from yasuki_web.schemas import IntentEnvelope
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneKey, ZoneRole, DeckKey, BoardPos
from yasuki_core.engine.intents import IntentOp
from yasuki_core.engine.action_log import ChatEntry, SessionEntry
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_web._support import account


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
def room():
    rooms["r1"] = {"players": [], "max_players": 2}
    try:
        yield GameRoom("r1")
    finally:
        rooms.pop("r1", None)


def _seat_two(room):
    ada, kenji = _FakeWS(), _FakeWS()
    asyncio.run(room.add_player(ada, account("Ada")))
    asyncio.run(room.add_player(kenji, account("Kenji")))
    return ada, kenji


def _hand_card(room, seat, card_id="f1", name="Secret"):
    card = L5RCard(id=card_id, name=name, side=Side.FATE, owner=seat, face_up=False)
    room.state.zones[ZoneKey(seat, ZoneRole.HAND)].cards.append(card)
    room.state.cards_by_id[card_id] = card
    return card


def test_first_two_players_get_distinct_seats(room):
    ada, kenji = _seat_two(room)
    assert room.seats == {ada: PlayerId.P1, kenji: PlayerId.P2}
    assert ada.sent[0]["your_seat"] == "P1"
    assert kenji.sent[0]["your_seat"] == "P2"


def test_third_player_is_rejected_as_table_full(room):
    _seat_two(room)
    third = _FakeWS()
    asyncio.run(room.add_player(third, account("Shiro")))
    assert third not in room.seats
    assert third.sent[-1]["type"] == "ERROR"


def test_leaving_frees_the_seat_for_a_new_player(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.remove_player(ada))
    shiro = _FakeWS()
    asyncio.run(room.add_player(shiro, account("Shiro")))
    assert room.seats[shiro] is PlayerId.P1  # P1 reopened


def test_each_seat_receives_its_own_redacted_snapshot(room):
    ada, kenji = _seat_two(room)
    _hand_card(room, PlayerId.P1)  # Ada's face-down hand card

    asyncio.run(room.broadcast_snapshots())

    ada_hand = ada.sent[-1]["snapshot"]["zones"]["P1:hand"][0]
    kenji_hand = kenji.sent[-1]["snapshot"]["zones"]["P1:hand"][0]
    assert ada_hand["name"] == "Secret"  # owner sees their own card
    # The opponent gets a stub: the public owner and show state, but no identity.
    assert kenji_hand == {
        "id": "f1",
        "side": "FATE",
        "owner": "P1",
        "token": False,
        "hidden": True,
        "shown": False,
    }


def test_accepted_intent_mutates_logs_and_broadcasts_to_both(room):
    ada, kenji = _seat_two(room)
    before = len(room.action_log.entries)

    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.SET_HONOR, value=20)))

    assert room.state.seats[PlayerId.P1].honor == 20
    assert len(room.action_log.entries) == before + 1
    assert kenji.sent[-1]["type"] == "LOG"
    assert kenji.sent[-1]["parts"] == [{"text": "Ada "}, {"text": "set their honor to 20"}]
    assert any(m["type"] == "SNAPSHOT" for m in kenji.sent)


def test_opponent_targeting_intent_is_rejected_and_unlogged(room):
    ada, kenji = _seat_two(room)
    _hand_card(room, PlayerId.P2, name="Theirs")  # belongs to Kenji
    before = len(room.action_log.entries)
    kenji.sent.clear()

    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.FLIP, card_ids=["f1"])))

    assert any(m["type"] == "ERROR" for m in ada.sent)
    assert len(room.action_log.entries) == before  # nothing recorded
    assert kenji.sent == []  # a rejected intent broadcasts nothing to the other seat


def test_move_deck_top_routes_through_the_websocket(room):
    ada, _ = _seat_two(room)
    deck = room.state.decks[DeckKey(PlayerId.P1, Side.FATE)]
    top = L5RCard(id="t1", name="Top", side=Side.FATE, owner=PlayerId.P1, face_up=False)
    deck.cards.append(top)
    room.state.cards_by_id["t1"] = top

    asyncio.run(
        room.handle_intent(
            ada,
            IntentEnvelope(
                op=IntentOp.MOVE_DECK_TOP,
                deck={"owner": "P1", "side": "FATE"},
                to={"kind": "battlefield"},
                position=[4.0, 5.0],
            ),
        )
    )

    assert top in room.state.battlefield.cards
    assert room.state.positions["t1"] == BoardPos(4.0, 5.0)
    assert deck.cards == []
    assert any(m["type"] == "SNAPSHOT" for m in ada.sent)  # the accepted move was broadcast


def test_play_face_down_hides_the_card_from_the_opponent_but_not_its_owner(room):
    ada, kenji = _seat_two(room)
    card = L5RCard(id="f1", name="Secret", side=Side.FATE, owner=PlayerId.P1, face_up=True)
    room.state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)].cards.append(card)
    room.state.cards_by_id["f1"] = card
    kenji.sent.clear()

    asyncio.run(
        room.handle_intent(
            ada,
            IntentEnvelope(
                op=IntentOp.MOVE_CARD,
                card_id="f1",
                to={"kind": "battlefield"},
                position=[4.0, 5.0],
                face_down=True,
            ),
        )
    )

    assert card in room.state.battlefield.cards
    assert card.face_up is False
    assert PlayerId.P1 in card.peekers  # its owner still reads their own focused card

    # The opponent's snapshot conceals the card entirely — a face-down play is the focus mechanic, so
    # Kenji must see only a back — while Ada's still shows it, revealed by the auto-peek.
    def battlefield_card(ws):
        snapshot = next(m for m in reversed(ws.sent) if m["type"] == "SNAPSHOT")["snapshot"]
        return next(c for c in snapshot["battlefield"] if c["id"] == "f1")

    assert battlefield_card(kenji)["hidden"] is True
    assert "name" not in battlefield_card(kenji)
    assert battlefield_card(ada)["name"] == "Secret"
    assert battlefield_card(ada)["peeked"] is True

    # The shared log names no card — a face-down play must not leak the identity to the opponent.
    log = next(m for m in kenji.sent if m["type"] == "LOG")
    assert log["parts"] == [{"text": "Ada "}, {"text": "plays a face-down fate card"}]


def _battlefield_card(room, card_id, seat=PlayerId.P1):
    card = L5RCard(id=card_id, name=card_id, side=Side.DYNASTY, owner=seat, face_up=True)
    room.state.battlefield.cards.append(card)
    room.state.positions[card_id] = BoardPos(0.0, 0.0)
    room.state.cards_by_id[card_id] = card
    return card


def test_attach_envelope_round_trips_through_to_the_snapshot(room):
    # The generic envelope `to` dict already carries an attach target, so no schema field was added;
    # this exercises the whole path envelope -> decode -> apply -> redact -> serialized snapshot.
    ada, kenji = _seat_two(room)
    _battlefield_card(room, "parent")
    _battlefield_card(room, "child")
    kenji.sent.clear()

    asyncio.run(
        room.handle_intent(
            ada,
            IntentEnvelope(
                op=IntentOp.ATTACH, card_id="child", to={"kind": "card", "card_id": "parent"}
            ),
        )
    )

    assert room.state.attachments == {"child": "parent"}
    snapshot = next(m for m in reversed(kenji.sent) if m["type"] == "SNAPSHOT")["snapshot"]
    assert snapshot["attachments"] == {"child": {"card": "parent"}}


def test_detach_envelope_clears_the_attachment(room):
    ada, _ = _seat_two(room)
    _battlefield_card(room, "parent")
    _battlefield_card(room, "child")
    asyncio.run(
        room.handle_intent(
            ada,
            IntentEnvelope(
                op=IntentOp.ATTACH, card_id="child", to={"kind": "card", "card_id": "parent"}
            ),
        )
    )

    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.DETACH, card_id="child")))

    assert room.state.attachments == {}


def test_chat_is_recorded_on_the_durable_tape(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.handle_chat(ada, "hello"))

    chats = [e for e in room.action_log.entries if isinstance(e, ChatEntry)]
    assert len(chats) == 1
    assert (chats[0].sender, chats[0].text) == ("Ada", "hello")


def test_chat_and_intents_share_one_ordered_tape(room):
    ada, _ = _seat_two(room)
    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.CREATE_PROVINCE)))
    asyncio.run(room.handle_chat(ada, "made a province"))
    asyncio.run(room.handle_intent(ada, IntentEnvelope(op=IntentOp.SET_HONOR, value=5)))

    # Ignoring the session (join) entries, the chat lands between the two intents on one tape.
    kinds = [
        "chat" if isinstance(entry, ChatEntry) else "intent"
        for entry in room.action_log.entries
        if not isinstance(entry, SessionEntry)
    ]
    assert kinds == ["intent", "chat", "intent"]


# --- the room owns its randomness -----------------------------------------------------------------


def _rolls(room, ws, count, sides=1000):
    """Roll ``count`` dice through the public intent path and return the announced faces."""
    faces = []
    for _ in range(count):
        asyncio.run(room.handle_intent(ws, IntentEnvelope(op=IntentOp.ROLL_DICE, value=sides)))
        faces.append(room.log_history[-1]["parts"][-1]["text"])
    return faces


def test_a_seat_rolls_a_different_face_each_time(room):
    """A generator rebuilt per intent instead of advanced would announce the same face forever, and
    a d1000 makes that unmistakable rather than a plausible run of luck."""
    ada, _ = _seat_two(room)

    assert len(set(_rolls(room, ada, 10))) > 1


def test_the_seats_do_not_draw_the_same_sequence(room):
    """Spawned streams, not one seed copied per seat: two players rolling in lockstep would be
    obvious at the table and is the failure mode a shared seed produces."""
    ada, kenji = _seat_two(room)

    assert _rolls(room, ada, 5) != _rolls(room, kenji, 5)


def test_one_seat_rolling_does_not_move_the_other_seats_stream(monkeypatch, room):
    """Why the seats get spawned streams rather than sharing one: an opponent's dice must not shift
    the faces you were going to roll."""
    monkeypatch.setattr(ws_module, "SeedSequence", lambda: SeedSequence(4321))

    room._new_game_rng()
    ada, kenji = _seat_two(room)
    undisturbed = _rolls(room, kenji, 3)

    room._new_game_rng()
    _rolls(room, ada, 5)  # the opponent rolls first this time

    assert _rolls(room, kenji, 3) == undisturbed


def test_a_new_game_draws_a_new_seed(room):
    """One seed per game: replaying a room's reset must not deal the same board again."""
    first = room.game_seed

    room._clear_table()

    assert room.game_seed != first
