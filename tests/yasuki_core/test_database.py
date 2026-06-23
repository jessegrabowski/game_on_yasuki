import psycopg
import pytest

from yasuki_core.database import (
    _is_private_dsn,
    mask_dsn,
    search_cards,
    get_card_by_id,
    query_all_prints,
    get_prints_by_card_id,
    query_cards_filtered,
    query_cards_page,
    count_cards_filtered,
    query_random_cards,
    query_stat_ranges,
    query_types_with_stat,
    get_card_backs,
    get_connection_string,
)
from yasuki_core.paths import SETS_DIR, resolve_set_image_path

# Card images are gitignored and served from R2, so they're absent in CI and fresh clones; only
# assert on-disk existence when the local image tree is actually populated.
_IMAGES_PRESENT = SETS_DIR.exists() and any(SETS_DIR.iterdir())


def _db_available():
    try:
        conn = psycopg.connect(get_connection_string())
        conn.close()
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


@pytest.fixture
def kuni_yori_cards():
    """Fixture providing all Kuni Yori card versions."""
    cards = search_cards(query="Kuni Yori")
    return [c for c in cards if c["name"] == "Kuni Yori"]


def test_query_all_cards_returns_list():
    """Test that card queries return card dictionaries with expected fields."""
    cards, total = query_cards_page(limit=5)

    assert total > 0
    assert len(cards) == 5

    first_card = cards[0]
    assert "card_id" in first_card
    assert "name" in first_card
    assert "decks" in first_card
    assert "types" in first_card
    assert set(first_card["decks"]).issubset({"Fate", "Dynasty", "Pre-Game", "Other"})


def test_search_cards_with_query():
    """Test searching cards with a text query."""
    results = search_cards(query="Crane")

    assert isinstance(results, list)
    assert len(results) > 0

    for card in results:
        card_text = (card["name"] + " " + (card["text"] or "")).lower()
        assert "crane" in card_text


def test_search_cards_with_deck_filter():
    """Test filtering cards by deck type."""
    fate_cards = search_cards(query="Crane", deck_filter="Fate")
    dynasty_cards = search_cards(query="Crane", deck_filter="Dynasty")

    assert len(fate_cards) > 0
    assert len(dynasty_cards) > 0
    assert all("Fate" in card["decks"] for card in fate_cards)
    assert all("Dynasty" in card["decks"] for card in dynasty_cards)


def test_search_cards_combined_filters():
    """Test combining query and deck filter."""
    results = search_cards(query="Lion", deck_filter="Dynasty")

    assert all("Dynasty" in card["decks"] for card in results)
    for card in results:
        card_text = (card["name"] + " " + (card["text"] or "")).lower()
        assert "lion" in card_text


def test_get_card_by_id():
    """Test fetching a single card by ID."""
    cards, total = query_cards_page(limit=1)
    assert total > 0

    test_id = cards[0]["card_id"]
    card = get_card_by_id(test_id)

    assert card is not None
    assert card["card_id"] == test_id
    assert "name" in card
    assert "decks" in card
    assert "types" in card


def test_get_card_by_invalid_id():
    """Test that fetching a non-existent card returns None."""
    card = get_card_by_id("this-card-does-not-exist-12345")
    assert card is None


def test_query_all_prints_returns_multiple_prints_per_card():
    prints = query_all_prints()
    assert len(prints) > 0

    sample = prints[0]
    assert "print_id" in sample
    assert "set_name" in sample
    assert "image_path" in sample
    assert "card_id" in sample
    assert "name" in sample
    assert "decks" in sample


def test_kuni_yori_different_versions_as_separate_cards(kuni_yori_cards):
    """Test that different versions of Kuni Yori are separate cards with unique IDs."""
    assert len(kuni_yori_cards) > 1

    card_ids = [c["card_id"] for c in kuni_yori_cards]
    assert len(card_ids) == len(set(card_ids)), "Card IDs should be unique"

    stats = [(c["force"], c["chi"], c["gold_cost"]) for c in kuni_yori_cards]
    assert len(set(stats)) > 1, "Different versions should have different stats"


def test_get_prints_by_card_id(kuni_yori_cards):
    """Test getting prints for a specific card ID."""
    assert len(kuni_yori_cards) > 0, "Should find at least one Kuni Yori card"

    test_card_id = kuni_yori_cards[0]["card_id"]
    prints = get_prints_by_card_id(test_card_id)

    assert len(prints) >= 1

    for p in prints:
        assert "print_id" in p
        assert "card_id" in p
        assert p["card_id"] == test_card_id
        assert "set_name" in p


class TestSQLFiltering:
    """Test SQL-based card filtering."""

    def test_query_all_cards_no_filters(self):
        """Should return all cards when no filters applied."""
        count = count_cards_filtered()
        assert count > 0
        cards, total = query_cards_page(limit=5)
        assert total == count
        assert all("card_id" in c and "name" in c for c in cards)

    def test_text_search(self):
        """Should filter by card name, ID, or rules text."""
        cards = query_cards_filtered(text_query="Doji")
        assert len(cards) > 0
        assert all(
            "doji" in c["name"].lower()
            or "doji" in c["card_id"].lower()
            or (c.get("text") and "doji" in c["text"].lower())
            for c in cards
        )

    def test_filter_by_clan(self):
        """Should filter by clan membership."""
        cards = query_cards_filtered(filter_options={"clans": ["Crane"]})
        assert len(cards) > 0
        assert all("Crane" in (c["clans"] or []) for c in cards)

    def test_filter_by_clan_is_case_insensitive(self):
        """clan:crane should match the same cards as clan:Crane."""
        lower = {c["card_id"] for c in query_cards_filtered(filter_options={"clans": ["crane"]})}
        proper = {c["card_id"] for c in query_cards_filtered(filter_options={"clans": ["Crane"]})}
        assert lower and lower == proper

    def test_filter_by_type(self):
        """Should filter by card type."""
        cards = query_cards_filtered(filter_options={"types": ["Personality"]})
        assert len(cards) > 0
        assert all("Personality" in c["types"] for c in cards)

    def test_filter_by_deck(self):
        """Should filter by deck type."""
        cards = query_cards_filtered(filter_options={"decks": ["Fate"]})
        assert len(cards) > 0
        assert all("Fate" in c["decks"] for c in cards)

    def test_filter_by_unique(self):
        """Should filter by is_unique boolean."""
        cards = query_cards_filtered(filter_options={"is_unique": True})
        assert len(cards) > 0
        assert all(c["is_unique"] is True for c in cards)

    def test_combined_filters(self):
        """Should apply multiple filters together."""
        cards = query_cards_filtered(
            filter_options={
                "clans": ["Crane"],
                "types": ["Personality"],
            }
        )
        assert len(cards) > 0
        assert all("Crane" in (c["clans"] or []) and "Personality" in c["types"] for c in cards)

    def test_text_search_with_filters(self):
        """Should combine text search with property filters."""
        cards = query_cards_filtered(text_query="Doji", filter_options={"types": ["Personality"]})
        assert len(cards) > 0
        for card in cards:
            assert (
                "doji" in card["name"].lower()
                or "doji" in card["card_id"].lower()
                or (card.get("text") and "doji" in card["text"].lower())
            )
            assert "Personality" in card["types"]

    def test_filter_by_legality(self):
        """Should filter by format legality using subquery."""
        cards = query_cards_filtered(
            filter_options={"legality": ("A Brother's Destiny (Ivory Edition)", None)}
        )
        assert isinstance(cards, list)
        assert all("card_id" in c for c in cards)

    def test_no_matches_returns_empty_list(self):
        """Should return empty list when no cards match filters."""
        cards = query_cards_filtered(text_query="XYZ_IMPOSSIBLE_MATCH_9999")
        assert cards == []

    def test_none_filter_value_ignored(self):
        """Should ignore filters with None values."""
        all_count = count_cards_filtered()
        filtered_count = count_cards_filtered(filter_options={"clan": None})
        assert all_count == filtered_count

    def test_results_include_image_path(self):
        """Should include an image_path of the served form sets/<slug>/<file> (or None)."""
        cards, _ = query_cards_page(limit=5)
        for card in cards:
            assert "image_path" in card
            if card["image_path"]:
                assert card["image_path"].startswith("sets/")
                resolved = resolve_set_image_path(card["image_path"])
                assert resolved is not None
                if _IMAGES_PRESENT:
                    assert resolved.exists()


class TestCardBacks:
    def test_get_card_backs_returns_five(self):
        backs = get_card_backs()
        assert set(backs) == {
            ("Fate", "old"),
            ("Fate", "new"),
            ("Dynasty", "old"),
            ("Dynasty", "new"),
            ("Dynasty", "token"),
        }
        for path in backs.values():
            assert path.startswith("sets/backs/")
            if _IMAGES_PRESENT:
                assert resolve_set_image_path(path).exists()


class TestLikeEscaping:
    """Verify that LIKE/ILIKE wildcard characters are escaped in user input."""

    def test_percent_search_does_not_match_all(self):
        all_count = count_cards_filtered()
        pct_count = count_cards_filtered(text_query="%")
        assert pct_count < all_count

    def test_underscore_search_does_not_match_single_chars(self):
        all_count = count_cards_filtered()
        under_count = count_cards_filtered(text_query="___")
        assert under_count < all_count

    def test_search_cards_percent(self):
        all_count = count_cards_filtered()
        pct_results = search_cards(query="%")
        assert len(pct_results) < all_count


class TestPagination:
    """Test SQL-level pagination via query_cards_page."""

    def test_custom_limit(self):
        cards, total = query_cards_page(limit=10)
        assert len(cards) == 10
        assert total > 10

    def test_offset_pages_do_not_overlap(self):
        page1, total1 = query_cards_page(limit=5, offset=0)
        page2, total2 = query_cards_page(limit=5, offset=5)
        assert total1 == total2
        ids1 = {c["card_id"] for c in page1}
        ids2 = {c["card_id"] for c in page2}
        assert ids1.isdisjoint(ids2)

    def test_offset_beyond_total_returns_empty(self):
        cards, total = query_cards_page(limit=10, offset=999999)
        assert cards == []
        assert total > 0

    def test_filters_reduce_total(self):
        _, all_total = query_cards_page(limit=1)
        _, crane_total = query_cards_page(
            filter_options={"clans": ["Crane"]},
            limit=1,
        )
        assert 0 < crane_total < all_total

    def test_text_query_with_pagination(self):
        cards, total = query_cards_page(text_query="Doji", limit=5)
        assert total > 0
        assert len(cards) == 5

    def test_no_matches_returns_zero(self):
        cards, total = query_cards_page(text_query="XYZ_IMPOSSIBLE_9999", limit=10)
        assert cards == []
        assert total == 0


class TestCountCardsFiltered:
    """Test count-only query (no data fetch)."""

    def test_count_with_filter(self):
        count = count_cards_filtered(filter_options={"clans": ["Crane"]})
        cards = query_cards_filtered(filter_options={"clans": ["Crane"]})
        assert count == len(cards)

    def test_count_no_match(self):
        assert count_cards_filtered(text_query="XYZ_IMPOSSIBLE_9999") == 0


class TestRandomCards:
    """Test SQL-level random card sampling."""

    def test_returns_requested_count(self):
        cards = query_random_cards(5)
        assert len(cards) == 5

    def test_deck_filter(self):
        cards = query_random_cards(10, deck_filter="Fate")
        assert all("Fate" in c["decks"] for c in cards)

    def test_returns_different_results(self):
        ids1 = {c["card_id"] for c in query_random_cards(20)}
        ids2 = {c["card_id"] for c in query_random_cards(20)}
        assert ids1 != ids2


def test_query_stat_ranges():
    """Test that query_stat_ranges returns min/max for all statistics."""
    ranges = query_stat_ranges()

    assert isinstance(ranges, dict)

    expected_stats = [
        "force",
        "chi",
        "honor_requirement",
        "gold_cost",
        "personal_honor",
        "province_strength",
        "gold_production",
        "starting_honor",
        "focus",
    ]

    for stat in expected_stats:
        assert stat in ranges, f"{stat} should be in ranges"
        min_val, max_val = ranges[stat]
        assert isinstance(min_val, int), f"{stat} min should be int"
        assert isinstance(max_val, int), f"{stat} max should be int"
        assert min_val <= max_val, f"{stat} min should be <= max"


def test_query_types_with_stat_force():
    """Test finding types and decks that have force stat."""
    types, decks = query_types_with_stat("force")

    assert isinstance(types, list)
    assert isinstance(decks, list)
    assert "Personality" in types
    assert "Stronghold" not in types
    assert "Dynasty" in decks


def test_query_types_with_stat_starting_honor():
    """Test finding types and decks that have starting_honor stat."""
    types, decks = query_types_with_stat("starting_honor")

    assert isinstance(types, list)
    assert isinstance(decks, list)

    assert "Stronghold" in types
    assert "Personality" not in types


def test_query_types_with_stat_invalid():
    """Test that invalid stat names raise an error."""
    with pytest.raises(ValueError, match="Invalid stat name"):
        query_types_with_stat("invalid_stat")

    with pytest.raises(ValueError, match="Invalid stat name"):
        query_types_with_stat("id")


@pytest.mark.parametrize(
    "filter_options",
    [
        {"keywords": ["cavalry"]},
        {"keywords": ["cavalry", "experienced"]},
        {"keywords": ["cavalry"], "clans": ["Unicorn"], "force": (3, None)},
        {"is_unique": True},
        {"is_unique": True, "keywords": ["experienced"]},
    ],
    ids=[
        "single_keyword",
        "multiple_keywords",
        "keyword_with_other_filters",
        "is_unique_alone",
        "is_unique_and_keyword",
    ],
)
def test_keyword_and_unique_filters(filter_options):
    """Test that keyword and is_unique filters produce valid results."""
    results = query_cards_filtered("", filter_options)

    assert isinstance(results, list)
    if filter_options.get("is_unique"):
        for card in results:
            assert card.get("is_unique") is True


def test_double_faced_search_matches_back_returns_front():
    # The Dark Capital of the Spider's back face says "lose 2 Honor less" (the front says "1 Honor
    # less"). A rules search for the back's text must still return the front card, never a back row.
    ids = {
        c["card_id"] for c in query_cards_filtered("", {"rules_text_contains": ["2 Honor less"]})
    }
    assert "the_dark_capital_of_the_spider" in ids
    assert not any(i.endswith("__back") for i in ids)


def test_double_faced_stat_matches_either_face():
    # Dark Capital's province_strength is 7 on the front, 9 on the back; ps:9 must find it via the
    # back and return the front.
    ids = {c["card_id"] for c in query_cards_filtered("", {"province_strength": (9, 9)})}
    assert "the_dark_capital_of_the_spider" in ids
    assert not any(i.endswith("__back") for i in ids)


def test_cross_face_filter_works_through_pagination_and_count():
    # A numeric filter yields a cross-face condition referencing the joined `back` row; the paginated
    # data query and both COUNT queries must include that join (regression: COUNT used a bare FROM
    # cards c and 500'd on `back.<col>`).
    options = {"province_strength": (9, 9)}
    cards, total = query_cards_page("", options, limit=60, offset=0)
    ids = {c["card_id"] for c in cards}
    assert "the_dark_capital_of_the_spider" in ids
    assert not any(i.endswith("__back") for i in ids)
    assert count_cards_filtered("", options) == total


def test_double_faced_flip_image_from_back_card():
    # The flip image resolves from the back card's matching printing (role='front' on the back's
    # print), not a role='back' image on the front print — and stays within the same printing's set.
    prints = get_prints_by_card_id("the_dark_capital_of_the_spider")
    assert prints
    for p in prints:
        assert p["back_image_path"] and p["back_image_path"].endswith("__back.jpg")
        assert p["image_path"].rsplit("/", 1)[0] == p["back_image_path"].rsplit("/", 1)[0]


class TestPrivateDsnDetection:
    @pytest.mark.parametrize(
        "dsn",
        [
            "postgresql://localhost/yasuki",
            "postgresql://user:pass@localhost:5432/yasuki",
            "postgresql://user:pass@127.0.0.1:5432/yasuki",
            "postgresql://user:pass@db:5432/yasuki",
            "postgresql://user:pass@my-postgres:5432/yasuki",
            "postgresql://user:pass@10.0.0.5:5432/yasuki",
            "postgresql://user:pass@172.18.0.2:5432/yasuki",
            "postgresql://user:pass@192.168.1.100:5432/yasuki",
        ],
        ids=[
            "localhost",
            "localhost_with_port",
            "loopback",
            "docker_service_name",
            "docker_hyphenated",
            "rfc1918_10",
            "rfc1918_172",
            "rfc1918_192",
        ],
    )
    def test_private_hosts_detected(self, dsn):
        assert _is_private_dsn(dsn) is True

    @pytest.mark.parametrize(
        "dsn",
        [
            "postgresql://user:pass@roundhouse.proxy.rlwy.net:5432/railway",
            "postgresql://user:pass@db.railway.internal:5432/railway",
            "postgresql://user:pass@44.200.1.5:5432/yasuki",
        ],
        ids=["railway_proxy", "railway_internal", "public_ip"],
    )
    def test_public_hosts_not_private(self, dsn):
        assert _is_private_dsn(dsn) is False

    @pytest.mark.parametrize(
        "dsn, expected",
        [
            (
                "postgresql://user:s3cret@host:5432/db",
                "postgresql://user:****@host:5432/db",
            ),
            (
                "postgresql://localhost/yasuki",
                "postgresql://localhost/yasuki",
            ),
        ],
        ids=["with_password", "no_password"],
    )
    def test_mask_dsn(self, dsn, expected):
        assert mask_dsn(dsn) == expected
