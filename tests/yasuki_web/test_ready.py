import asyncio

import pytest

from yasuki_web import websocket as ws_module
from yasuki_web.websocket import GameRoom
from yasuki_web.rooms import rooms
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_web._support import account

# Card records shaped like database.get_cards_by_names output; the fetch is faked in the room fixture.
RECORDS = [
    {
        "card_id": "kyuden_hida",
        "name": "Kyuden Hida",
        "extended_title": "Kyuden Hida",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
        "starting_honor": 10,
        "prints": [{"print_id": 1, "set_name": "IE", "image_path": "sets/ie/kh.png"}],
    },
    {
        "card_id": "kuni_yori",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori",
        "types": ["Personality"],
        "decks": ["Dynasty"],
        "prints": [{"print_id": 2, "set_name": "IE", "image_path": "sets/ie/ky.png"}],
    },
    {
        "card_id": "ambush",
        "name": "Ambush",
        "extended_title": "Ambush",
        "types": ["Strategy"],
        "decks": ["Fate"],
        "prints": [{"print_id": 3, "set_name": "IE", "image_path": "sets/ie/a.png"}],
    },
]

# Decks sized to outlast the opening deal (4 provinces + 5-card starting hand): dynasty keeps
# 10 - 4 = 6 and fate keeps 10 - 5 = 5.
DECK_YAML = (
    "name: D\nPre-Game:\n  - Kyuden Hida\nDynasty:\n  - 10x Kuni Yori\nFate:\n  - 10x Ambush\n"
)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
def room(monkeypatch):
    monkeypatch.setattr(ws_module, "get_cards_by_names", lambda names: RECORDS)
    rooms["r1"] = {"players": [], "max_players": 2}
    try:
        yield GameRoom("r1")
    finally:
        rooms.pop("r1", None)


def _seat(room, name):
    ws = _FakeWS()
    asyncio.run(room.add_player(ws, account(name)))
    return ws


def _both_loaded(room):
    ada, kenji = _seat(room, "Ada"), _seat(room, "Kenji")
    asyncio.run(room.handle_load_deck(ada, DECK_YAML))
    asyncio.run(room.handle_load_deck(kenji, DECK_YAML))
    return ada, kenji


def test_one_ready_seat_does_not_trigger_setup(room):
    ada, _ = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    assert not room.setup_done


def test_solo_ready_deals_a_one_seat_goldfish_table(room):
    ada = _seat(room, "Ada")
    asyncio.run(room.handle_load_deck(ada, DECK_YAML))
    asyncio.run(room.handle_ready(ada, True, solo=True))

    assert room.setup_done
    assert len(room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards) == 6
    assert room.state.decks[DeckKey(PlayerId.P2, Side.DYNASTY)].cards == []  # no opponent dealt


def test_a_lone_ready_without_solo_waits_for_an_opponent(room):
    ada = _seat(room, "Ada")
    asyncio.run(room.handle_load_deck(ada, DECK_YAML))
    asyncio.run(room.handle_ready(ada, True))
    assert not room.setup_done


def test_reset_needs_every_seated_player_to_agree(room):
    ada, kenji = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))
    assert room.setup_done

    asyncio.run(room.handle_reset(ada))  # one vote — table stands
    assert room.setup_done
    assert room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards != []

    asyncio.run(room.handle_reset(kenji))  # both agree — table clears
    assert not room.setup_done
    assert room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards == []
    assert not room.state.seats[PlayerId.P1].ready

    # Decks are kept, so readying again deals a fresh game without reloading.
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))
    assert room.setup_done
    assert len(room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards) == 6


def test_a_solo_goldfisher_resets_on_their_own(room):
    ada = _seat(room, "Ada")
    asyncio.run(room.handle_load_deck(ada, DECK_YAML))
    asyncio.run(room.handle_ready(ada, True, solo=True))
    assert room.setup_done

    asyncio.run(room.handle_reset(ada))  # lone seat — unanimous
    assert not room.setup_done
    assert room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards == []


def test_both_ready_deals_the_table_and_broadcasts(room):
    ada, kenji = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))

    assert room.setup_done
    assert len(room.state.decks[DeckKey(PlayerId.P1, Side.DYNASTY)].cards) == 6
    assert len(room.state.decks[DeckKey(PlayerId.P2, Side.FATE)].cards) == 5
    assert ada.sent[-1]["type"] == "SNAPSHOT"


def test_the_deal_fills_provinces_and_draws_the_starting_hand(room):
    ada, kenji = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))

    # The deck-count tests only prove cards left the decks; assert where they landed.
    hand = room.state.zones[ZoneKey(PlayerId.P1, ZoneRole.HAND)]
    assert len(hand.cards) == 5  # Kyuden Hida's default starting_hand_size
    provinces = [
        zone
        for key, zone in room.state.zones.items()
        if key.owner is PlayerId.P1 and key.role is ZoneRole.PROVINCE
    ]
    assert len(provinces) == 4
    assert all(len(province.cards) == 1 for province in provinces)


def test_readying_without_a_deck_is_rejected(room):
    ada = _seat(room, "Ada")
    asyncio.run(room.handle_ready(ada, True))
    assert ada.sent[-1]["type"] == "ERROR"
    assert not room.state.seats[PlayerId.P1].ready


def test_re_ready_after_setup_does_not_rerun_it(room):
    ada, kenji = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))
    log_after_setup = room.action_log

    asyncio.run(room.handle_ready(ada, True))

    assert room.action_log is log_after_setup  # rerunning setup would re-seed a new log


def test_setup_snapshot_holds_redaction_and_honor(room):
    ada, kenji = _both_loaded(room)
    asyncio.run(room.handle_ready(ada, True))
    asyncio.run(room.handle_ready(kenji, True))

    snapshot = ada.sent[-1]["snapshot"]
    assert snapshot["your_seat"] == "P1"
    assert snapshot["seats"]["P1"]["honor"] == 10  # from the stronghold
    # The face-down deck never leaks identities — count only, no top card.
    assert snapshot["decks"]["P1:dynasty"] == {"count": 6, "top": None}
    # The stronghold is a public, face-up loose pre-game card on the battlefield.
    stronghold = next(c for c in snapshot["battlefield"] if c.get("name") == "Kyuden Hida")
    assert stronghold["pregame"] is True
