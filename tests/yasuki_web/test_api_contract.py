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
        assert card["keywords"] is None or isinstance(
            card["keywords"], list
        )  # mon overlays read this
        assert "image_path" in card  # str path or None


def test_sort_orders_results(client):
    # The card-search page drives sort/order through these params; force ordering must actually flip.
    def forces(order):
        cards = client.get(f"/api/cards?search=type:personality&sort=force&order={order}").json()[
            "cards"
        ]
        return [c["force"] for c in cards if c["force"] is not None]

    desc = forces("desc")
    asc = forces("asc")
    assert desc == sorted(desc, reverse=True)
    assert asc == sorted(asc)
    assert desc[0] >= asc[0]


def test_unknown_sort_is_safe(client):
    # An out-of-whitelist sort key must fall back to name order, not error or inject SQL.
    body = client.get("/api/cards?sort=DROP+TABLE+cards&order=sideways&limit=5").json()
    names = [c["name"] for c in body["cards"]]
    assert names == sorted(names)


def _total(client, search):
    return client.get("/api/cards", params={"search": search, "limit": 1}).json()["total"]


def test_format_short_alias_resolves_in_sql(client):
    # `format:diamond` resolves via formats.block to the same cards as the full name.
    assert _total(client, "format:diamond") > 0
    assert _total(client, "format:diamond") == _total(client, 'format:"Rain of Blood (Diamond)"')


def test_format_inequality_uses_legal_from(client):
    gt = _total(client, "format>diamond")
    ge = _total(client, "format>=diamond")
    exact = _total(client, "format:diamond")
    assert ge > gt  # >= includes Diamond itself
    assert ge >= exact


def test_formats_endpoint_is_chronological(client):
    # Ordering comes from formats.legal_from, not a hardcoded list.
    body = client.get("/api/formats").json()
    assert body["arcs"][0] == "Clan Wars (Imperial)"
    assert body["arcs"][-1] == "Shattered Empire"
    assert body["other"][0] == "Modern"


def test_set_code_matches_full_name(client):
    # `set:GE` (code) resolves to the same cards as the full set name.
    assert _total(client, "set:GE") > 0
    assert _total(client, "set:GE") == _total(client, 'set:"Gold Edition"')


def test_set_inequality_uses_release_date(client):
    assert _total(client, "set>=GE") > _total(client, "set>GE")  # >= includes Gold Edition itself


def test_two_sided_set_range(client):
    # A range bounded on both sides is the intersection of the two inequalities.
    bounded = _total(client, "set>=GE set<=DE")
    assert 0 < bounded < _total(client, "set>=GE")


def test_two_sided_format_range(client):
    bounded = _total(client, "format>=gold format<=diamond")
    assert 0 < bounded < _total(client, "format>=gold")


def test_keyword_or_matches_union_not_everything(client):
    # is:a|b must match cards with EITHER keyword, not silently fall through to the whole catalog.
    either = _total(client, "is:cavalry|naval")
    cavalry = _total(client, "is:cavalry")
    naval = _total(client, "is:naval")
    everything = client.get("/api/cards?limit=1").json()["total"]
    assert max(cavalry, naval) <= either <= cavalry + naval
    assert either < everything


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
