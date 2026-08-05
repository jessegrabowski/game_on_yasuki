import psycopg
import pytest

from yasuki_core.database import get_connection_string
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_setup import build_state_from_deck

# The only real decklist in the repo is the one the desktop client bundles. Core has no deck asset
# of its own, and inventing one to avoid the import would be a second thing to keep current.
from yasuki_gui.session import DEMO_DECK_PATH


def _db_available():
    try:
        conn = psycopg.connect(get_connection_string())
        conn.close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


def _provinces(state, seat):
    return [k for k in state.zones if k.owner is seat and k.role is ZoneRole.PROVINCE]


def test_bundled_deck_deals_both_seats():
    state, human = build_state_from_deck(DEMO_DECK_PATH)
    assert human is PlayerId.P1
    for seat in PlayerId:
        assert len(_provinces(state, seat)) == 4
        assert state.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        assert state.decks[DeckKey(seat, Side.DYNASTY)].cards
        assert state.decks[DeckKey(seat, Side.FATE)].cards


def test_a_separate_opponent_deck_still_deals_both_seats():
    # The two decks resolve independently; passing the opponent path explicitly (here the same
    # bundled deck) still yields a fully dealt two-seat table.
    state, human = build_state_from_deck(DEMO_DECK_PATH, opponent_deck_path=DEMO_DECK_PATH)
    assert human is PlayerId.P1
    for seat in PlayerId:
        assert len(_provinces(state, seat)) == 4
        assert state.decks[DeckKey(seat, Side.DYNASTY)].cards


def test_a_mirror_match_resolves_the_deck_once(monkeypatch):
    # Both seats share a decklist, so the card lookup should happen once. Resolving twice is a
    # second round trip to the database for an answer already in hand.
    import yasuki_core.game_setup as game_setup

    real = game_setup.get_cards_by_names
    calls = []

    def counting(names):
        calls.append(names)
        return real(names)

    monkeypatch.setattr(game_setup, "get_cards_by_names", counting)
    build_state_from_deck(DEMO_DECK_PATH, opponent_deck_path=DEMO_DECK_PATH)

    assert len(calls) == 1


def test_bundled_deck_resolves_art_swaps():
    # The spider deck carries {art: ...} entries; resolving them against the DB attaches art_swap
    # payloads, the data the renderer needs for a custom printing.
    state, _ = build_state_from_deck(DEMO_DECK_PATH)
    assert any(card.art_swap for card in state.cards_by_id.values())
