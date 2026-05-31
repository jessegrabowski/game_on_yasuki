import psycopg
import pytest
from fastapi.testclient import TestClient

from yasuki_core.database import get_connection_string


def _db_available():
    try:
        psycopg.connect(get_connection_string()).close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


@pytest.fixture(scope="module")
def client():
    from yasuki_web.main import app

    return TestClient(app)


# The deck-builder JS consumes these exact keys; a server-side shape regression must fail here
# rather than only surfacing after a deploy.


def test_list_cards_shape(client):
    body = client.get("/api/cards?limit=3").json()
    assert {"cards", "total", "has_more"} <= body.keys()
    assert isinstance(body["total"], int) and isinstance(body["has_more"], bool)
    assert body["cards"], "expected at least one card"
    for card in body["cards"]:
        assert isinstance(card["card_id"], str) and card["card_id"]
        assert isinstance(card["name"], str)
        assert isinstance(card["decks"], list)
        assert isinstance(card["types"], list)
        assert card["clans"] is None or isinstance(card["clans"], list)
        assert "image_path" in card  # str path or None


def test_card_detail_shape(client):
    card_id = client.get("/api/cards?limit=1").json()["cards"][0]["card_id"]
    body = client.get(f"/api/cards/{card_id}").json()
    assert {"card", "prints", "print_count"} <= body.keys()
    assert body["card"]["card_id"] == card_id
    assert body["print_count"] == len(body["prints"])
    for print_ in body["prints"]:
        assert isinstance(print_["print_id"], int)
        assert "set_name" in print_
        assert "image_path" in print_  # served as sets/<slug>/<file> or None
        assert "back_image_path" in print_  # back face for double-sided prints, else None
        assert isinstance(print_["era"], str)  # art-swap era band, e.g. "2016+"
        assert isinstance(print_["layout_type"], str)  # art-swap layout, e.g. "Personality"
        assert print_["back_era"] in ("old", "new")  # which generic card back to flip to


def test_card_backs_shape(client):
    backs = client.get("/api/card-backs").json()["backs"]
    assert {"Fate", "Dynasty"} <= backs.keys()
    assert backs["Fate"]["new"].startswith("sets/backs/")


def test_double_sided_card_exposes_back_image(client):
    import yasuki_core.database as db

    with db.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT p.card_id FROM print_images i JOIN prints p ON p.print_id = i.print_id"
            " WHERE i.role = 'back' LIMIT 1"
        )
        card_id = cur.fetchone()["card_id"]
    prints = client.get(f"/api/cards/{card_id}").json()["prints"]
    assert any(p["back_image_path"] for p in prints)


def test_deck_types_are_title_case(client):
    deck_types = client.get("/api/decks").json()["deck_types"]
    assert set(deck_types) <= {"Dynasty", "Fate", "Pre-Game", "Other"}


def test_clans_and_types_are_lists(client):
    assert isinstance(client.get("/api/clans").json()["clans"], list)
    assert isinstance(client.get("/api/card-types").json()["card_types"], list)
