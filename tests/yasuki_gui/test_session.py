import psycopg
import pytest

from yasuki_core.database import get_connection_string
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import DeckKey, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_gui.session import build_state_from_deck


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
    state, human = build_state_from_deck()
    assert human is PlayerId.P1
    for seat in PlayerId:
        assert len(_provinces(state, seat)) == 4
        assert state.zones[ZoneKey(seat, ZoneRole.HAND)].cards
        assert state.decks[DeckKey(seat, Side.DYNASTY)].cards
        assert state.decks[DeckKey(seat, Side.FATE)].cards


def test_bundled_deck_resolves_art_swaps():
    # The spider deck carries {art: ...} entries; resolving them against the DB attaches art_swap
    # payloads, the data the renderer needs for a custom printing.
    state, _ = build_state_from_deck()
    assert any(card.art_swap for card in state.cards_by_id.values())
