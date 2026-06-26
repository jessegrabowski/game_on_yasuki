import asyncio

import pytest

from yasuki_web.websocket import GameRoom
from yasuki_web.schemas import IntentEnvelope
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import IntentOp, DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side


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
    asyncio.run(room.add_player(ada, "Ada"))
    asyncio.run(room.add_player(kenji, "Kenji"))
    return ada, kenji


def _stock_deck(room, seat, side, card_ids):
    # Cards are stored bottom-first; the last appended is the top of the deck (the next draw).
    deck = room.state.decks[DeckKey(seat, side)]
    for card_id in card_ids:
        card = L5RCard(id=card_id, name=f"Card {card_id}", side=side, owner=seat, face_up=False)
        deck.cards.append(card)
        room.state.cards_by_id[card_id] = card
    return deck


def _search(owner, side, value=None):
    return IntentEnvelope(
        op=IntentOp.SEARCH_DECK, deck={"owner": owner, "side": side.value}, value=value
    )


def test_owner_search_delivers_ordered_deck_to_actor_only(room):
    ada, kenji = _seat_two(room)
    _stock_deck(room, PlayerId.P1, Side.FATE, ["b1", "m2", "t3"])  # t3 ends up on top
    ada.sent.clear()
    kenji.sent.clear()

    asyncio.run(room.handle_intent(ada, _search("P1", Side.FATE)))

    contents = [m for m in ada.sent if m["type"] == "DECK_CONTENTS"]
    assert len(contents) == 1
    msg = contents[0]
    assert msg["deck"] == {"owner": "P1", "side": "FATE"}
    # Top of deck first: the last-stored card leads, full identity intact for the owner.
    assert [card["id"] for card in msg["cards"]] == ["t3", "m2", "b1"]
    assert msg["cards"][0]["name"] == "Card t3"
    # The opponent receives the normal snapshot/log but never the deck order.
    assert all(m["type"] != "DECK_CONTENTS" for m in kenji.sent)


def test_bounded_search_delivers_only_the_top_n_cards(room):
    ada, _ = _seat_two(room)
    _stock_deck(room, PlayerId.P1, Side.FATE, ["b1", "m2", "t3"])  # t3 is the top
    ada.sent.clear()

    asyncio.run(room.handle_intent(ada, _search("P1", Side.FATE, value=2)))

    msg = next(m for m in ada.sent if m["type"] == "DECK_CONTENTS")
    # Only the top two cards are revealed, top-first.
    assert [card["id"] for card in msg["cards"]] == ["t3", "m2"]


def test_non_owner_search_receives_no_contents(room):
    ada, _ = _seat_two(room)
    _stock_deck(room, PlayerId.P2, Side.FATE, ["x1", "x2"])  # Kenji's deck
    ada.sent.clear()

    asyncio.run(room.handle_intent(ada, _search("P2", Side.FATE)))

    assert all(m["type"] != "DECK_CONTENTS" for m in ada.sent)
    assert ada.sent[-1]["type"] == "ERROR"  # the ownership gate rejects the intent outright
