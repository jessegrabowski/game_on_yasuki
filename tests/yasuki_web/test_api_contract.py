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
        # int print_id of the default art, or None; the deck builder opens the preview on it.
        assert card["default_print_id"] is None or isinstance(card["default_print_id"], int)


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


def _ids(client, search):
    cards = client.get("/api/cards", params={"search": search, "limit": 200}).json()["cards"]
    return {c["card_id"] for c in cards}


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


def test_unknown_field_does_not_match_everything(client):
    # An unsupported field must not silently drop and return the whole catalog.
    everything = _total(client, "include:all")
    assert _total(client, "bogusfield:xyzzy") < everything
    assert _total(client, "arc:lotus") < everything  # aliases to format:lotus


def test_non_deck_cards_hidden_by_default(client):
    default = client.get("/api/cards?limit=1").json()["total"]
    with_tokens = _total(client, "include:tokens")
    everything = _total(client, "include:all")
    assert default < with_tokens <= everything


def test_keyword_or_matches_union_not_everything(client):
    # is:a|b must match cards with EITHER keyword, not silently fall through to the whole catalog.
    either = _total(client, "is:cavalry|naval")
    cavalry = _total(client, "is:cavalry")
    naval = _total(client, "is:naval")
    everything = client.get("/api/cards?limit=1").json()["total"]
    assert max(cavalry, naval) <= either <= cavalry + naval
    assert either < everything


def test_grouped_or_query_returns_the_union(client):
    # Cross-field OR with grouping — the whole query is the union of its two AND groups.
    crane_courtiers = _ids(client, "c:crane is:courtier")
    lion_commanders = _ids(client, "c:lion is:commander")
    combined = _ids(client, "(c:crane is:courtier) OR (c:lion is:commander)")
    assert crane_courtiers and lion_commanders
    assert combined == crane_courtiers | lion_commanders


def test_dialog_dropdown_ands_with_the_search_box(client):
    # The clan dropdown ANDs with the search query rather than OR-merging into it.
    combined = client.get(
        "/api/cards", params={"search": "t:personality", "clan": "Crane", "limit": 1}
    ).json()["total"]
    assert combined == _total(client, "c:crane t:personality")


def test_story_credit_search(client):
    # Story credits are searchable; the documented example must return its known matches.
    assert _total(client, 'story:"Paul Ashman"') == 6


def test_artist_and_flavor_search(client):
    everything = _total(client, "include:all")
    assert 0 < _total(client, "a:Hara") < everything  # print artist, via the a: alias
    assert 0 < _total(client, "ft:honor") < everything  # flavor text, via the ft: alias


def test_is_banned_filter(client):
    banned = _total(client, "is:banned")
    everything = _total(client, "include:all")
    assert 0 < banned < everything
    # Negation flips it: not-banned plus banned covers the (visible) catalog with no overlap.
    assert _total(client, "-is:banned") + banned == _total(client, "")


def test_dash_stat_search(client):
    # `hr:-` matches the dash honor requirement (NULL), a different set from hr:0, and its negation
    # plus itself partition the catalog.
    dash = _total(client, "hr:- include:all")
    not_dash = _total(client, "-hr:- include:all")
    everything = _total(client, "include:all")
    assert dash > 0
    assert dash != _total(client, "hr:0 include:all")  # the dash stat is not zero
    assert dash + not_dash == everything


def test_clan_matches_senseis(client):
    # Senseis carry clan as a keyword, not a clan field; the loader materialises it into card_clans
    # so clan: reaches them. (Previously every clan: query missed all senseis.)
    assert _total(client, "clan:Phoenix type:sensei include:all") > 0


def test_clan_all_marks_all_clans_senseis(client):
    # "All Clans" senseis are tagged with a single marker, searchable as clan:all.
    assert _total(client, "clan:all type:sensei include:all") > 0


def test_all_clans_sensei_appears_under_specific_clan(client):
    # An "All Clans" sensei is legal in any clan's deck, so a specific-clan filter surfaces it too.
    universal = _ids(client, "clan:all type:sensei include:all")
    assert universal
    assert universal <= _ids(client, "clan:Crane type:sensei include:all")


def test_naga_akasha_are_aliased(client):
    # Naga was renamed Akasha; a filter on either name matches the whole clan.
    naga = _ids(client, "clan:Naga include:all")
    akasha = _ids(client, "clan:Akasha include:all")
    assert naga and naga == akasha


def test_minor_clan_search(client):
    # Minor clans (Fox, etc.) live only as "<X> Clan" keywords and now resolve through card_clans.
    assert _total(client, "clan:Fox include:all") > 0


def test_clan_does_not_match_elemental_dragons(client):
    # A bare "Dragon" keyword on a non-sensei is an elemental dragon, not the Dragon Clan.
    dragon = _total(client, "clan:Dragon include:all")
    everything = _total(client, "include:all")
    assert dragon < everything
    cards = client.get(
        "/api/cards", params={"search": "clan:Dragon include:all", "limit": 200}
    ).json()["cards"]
    assert "Fire Dragon" not in {c["name"] for c in cards}


def _named(client, search, name):
    cards = client.get("/api/cards", params={"search": search, "limit": 50}).json()["cards"]
    return next(c for c in cards if c["name"] == name)


def test_default_print_is_arc_aware(client):
    # The default art follows the active arc: arc:shattered surfaces the Shattered Empire printing,
    # while no filter falls back to the earliest printing.
    base = _named(client, "name:Refugees", "Refugees")
    shattered = _named(client, "name:Refugees arc:shattered", "Refugees")
    assert base["default_print_id"] != shattered["default_print_id"]

    prints = client.get(f"/api/cards/{shattered['card_id']}").json()["prints"]
    shattered_print = next(p for p in prints if p["set_name"] == "Shattered Empire")
    assert shattered["default_print_id"] == shattered_print["print_id"]


def test_default_print_rotated_in_card_uses_recent_printing(client):
    # A card legal in the active format only by rotation (no printing in that format's own arc) must
    # default to its most recent in-era printing, not its oldest. The Future is Unwritten is legal
    # in Shattered via its Onyx reprint; it must not fall back to the 2003 Gold art.
    name = "The Future is Unwritten"
    card = _named(client, f'name:"{name}" arc:shattered', name)
    prints = client.get(f"/api/cards/{card['card_id']}").json()["prints"]
    onyx = next(p for p in prints if p["set_name"] == "Rise of Otosan Uchi")
    assert card["default_print_id"] == onyx["print_id"]


def test_prints_listed_chronologically(client):
    # Prints come back oldest-first by set release date; Refugees' first printing is Anvil of Despair.
    card_id = _named(client, "name:Refugees", "Refugees")["card_id"]
    prints = client.get(f"/api/cards/{card_id}").json()["prints"]
    assert prints[0]["set_name"] == "Anvil of Despair"


def test_card_detail_shape(client):
    card_id = client.get("/api/cards?limit=1").json()["cards"][0]["card_id"]
    body = client.get(f"/api/cards/{card_id}").json()
    assert {"card", "prints", "print_count"} <= body.keys()
    assert body["card"]["card_id"] == card_id
    assert body["print_count"] == len(body["prints"])
    for print_ in body["prints"]:
        assert isinstance(print_["print_id"], int)
        assert "set_name" in print_
        assert isinstance(print_["set_slug"], str)  # slug pins the printing in /card/{id}/{slug}
        assert "image_path" in print_  # served as sets/<slug>/<file> or None
        assert "back_image_path" in print_  # back face for double-sided prints, else None
        assert isinstance(print_["era"], str)  # art-swap era band, e.g. "2016+"
        assert isinstance(print_["layout_type"], str)  # art-swap layout, e.g. "Personality"
        assert print_["back_era"] in ("old", "new")  # which generic card back to flip to


def test_card_page_renders_og_tags(client):
    # The shareable /card page server-renders OpenGraph tags so links unfurl in chat. The set_slug in
    # the path pins which printing's art the tags point at; an unknown card is a 404.
    html = client.get("/card/refugees").text
    assert 'property="og:title" content="Refugees"' in html
    assert (
        'property="og:image"' in html and "sets/anvil_of_despair/refugees.jpg" in html
    )  # earliest
    assert 'name="twitter:card" content="summary_large_image"' in html

    pinned = client.get("/card/refugees/shattered_empire").text
    assert "sets/shattered_empire/refugees.jpg" in pinned

    assert client.get("/card/no_such_card_zzz").status_code == 404


def test_card_backs_shape(client):
    backs = client.get("/api/card-backs").json()["backs"]
    assert {"Fate", "Dynasty"} <= backs.keys()
    assert backs["Fate"]["new"].startswith("sets/backs/")


def test_double_sided_card_exposes_back_image(client):
    import yasuki_core.database as db

    with db.get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT card_id FROM cards WHERE back_card_id IS NOT NULL LIMIT 1")
        card_id = cur.fetchone()["card_id"]
    body = client.get(f"/api/cards/{card_id}").json()
    # The flip image resolves from the back card's printing, and the back face's data is exposed so
    # the page can flip the stats/text panel too.
    assert any(p["back_image_path"] for p in body["prints"])
    assert body["back"] and body["back"]["card_id"].endswith("__back")


def test_deck_types_are_title_case(client):
    deck_types = client.get("/api/decks").json()["deck_types"]
    assert set(deck_types) <= {"Dynasty", "Fate", "Pre-Game", "Other"}


def test_clans_and_types_are_lists(client):
    assert isinstance(client.get("/api/clans").json()["clans"], list)
    assert isinstance(client.get("/api/card-types").json()["card_types"], list)


def test_clan_dropdown_omits_all_clans_marker(client):
    # "All Clans" tags universal senseis, not a clan; offering it would duplicate the placeholder.
    assert "All Clans" not in client.get("/api/clans").json()["clans"]


def test_clan_dropdown_collapses_akasha_into_naga(client):
    # Naga and Akasha are the same clan; the dropdown offers only the Naga name.
    clans = client.get("/api/clans").json()["clans"]
    assert "Naga" in clans and "Akasha" not in clans


def test_clans_narrow_to_active_filters(client):
    # The clan dropdown offers only clans with a matching card under the other active filters, for
    # both the card_type and format params. Each offered clan resolves to a card; each dropped clan
    # resolves to none.
    all_clans = set(client.get("/api/clans").json()["clans"])

    typed = client.get("/api/clans?card_type=Personality").json()["clans"]
    assert set(typed) < all_clans  # personalities don't span every clan
    assert set(client.get("/api/clans?format=Shattered Empire").json()["clans"]) < all_clans

    assert client.get(f"/api/cards?card_type=Personality&clan={typed[0]}").json()["total"] > 0

    dropped = next(iter(all_clans - set(typed)))
    assert client.get(f"/api/cards?card_type=Personality&clan={dropped}").json()["total"] == 0
