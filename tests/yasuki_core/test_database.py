import psycopg
import pytest

from yasuki_core.database import (
    _extract_host,
    _is_private_dsn,
    mask_dsn,
    query_all_cards,
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
    get_connection_string,
)


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
    cards = query_all_cards()
    return [c for c in cards if c["name"] == "Kuni Yori"]


def test_query_all_cards_returns_list():
    """Test that query_all_cards returns a list of card dictionaries."""
    cards = query_all_cards()

    assert isinstance(cards, list)
    assert len(cards) > 0

    first_card = cards[0]
    assert "id" in first_card
    assert "name" in first_card
    assert "side" in first_card
    assert "type" in first_card
    assert first_card["side"] in ("FATE", "DYNASTY", "PRE_GAME", "OTHER")


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
    fate_cards = search_cards(deck_filter="FATE")
    dynasty_cards = search_cards(deck_filter="DYNASTY")

    assert all(card["side"] == "FATE" for card in fate_cards)
    assert all(card["side"] == "DYNASTY" for card in dynasty_cards)


def test_search_cards_combined_filters():
    """Test combining query and deck filter."""
    results = search_cards(query="Lion", deck_filter="DYNASTY")

    assert all(card["side"] == "DYNASTY" for card in results)
    for card in results:
        card_text = (card["name"] + " " + (card["text"] or "")).lower()
        assert "lion" in card_text


def test_get_card_by_id():
    """Test fetching a single card by ID."""
    all_cards = query_all_cards()
    assert len(all_cards) > 0

    test_id = all_cards[0]["id"]
    card = get_card_by_id(test_id)

    assert card is not None
    assert card["id"] == test_id
    assert "name" in card
    assert "side" in card
    assert "type" in card


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
    assert "id" in sample
    assert "name" in sample
    assert "side" in sample


def test_kuni_yori_different_versions_as_separate_cards(kuni_yori_cards):
    """Test that different versions of Kuni Yori are separate cards with unique IDs."""
    assert len(kuni_yori_cards) > 1

    card_ids = [c["id"] for c in kuni_yori_cards]
    assert len(card_ids) == len(set(card_ids)), "Card IDs should be unique"

    stats = [(c["force"], c["chi"], c["gold_cost"]) for c in kuni_yori_cards]
    assert len(set(stats)) > 1, "Different versions should have different stats"


def test_get_prints_by_card_id(kuni_yori_cards):
    """Test getting prints for a specific card ID."""
    assert len(kuni_yori_cards) > 0, "Should find at least one Kuni Yori card"

    test_card_id = kuni_yori_cards[0]["id"]
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
        cards = query_cards_filtered()
        assert len(cards) > 0
        assert all("id" in c and "name" in c for c in cards)

    def test_text_search(self):
        """Should filter by card name, ID, or rules text."""
        cards = query_cards_filtered(text_query="Doji")
        assert len(cards) > 0
        assert all(
            "doji" in c["name"].lower()
            or "doji" in c["id"].lower()
            or (c.get("text") and "doji" in c["text"].lower())
            for c in cards
        )

    def test_filter_by_clan(self):
        """Should filter by clan property."""
        cards = query_cards_filtered(filter_options={"clan": "Crane"})
        assert len(cards) > 0
        assert all(c["clan"] == "Crane" for c in cards)

    def test_filter_by_type(self):
        """Should filter by card type with enum casting."""
        cards = query_cards_filtered(filter_options={"type": "Personality"})
        assert len(cards) > 0
        assert all(c["type"] == "Personality" for c in cards)

    def test_filter_by_deck(self):
        """Should filter by deck type with enum casting."""
        cards = query_cards_filtered(filter_options={"deck": "FATE"})
        assert len(cards) > 0
        assert all(c["side"] == "FATE" for c in cards)

    def test_filter_by_unique(self):
        """Should filter by is_unique boolean."""
        cards = query_cards_filtered(filter_options={"is_unique": True})
        assert len(cards) > 0
        assert all(c["is_unique"] is True for c in cards)

    def test_combined_filters(self):
        """Should apply multiple filters together."""
        cards = query_cards_filtered(
            filter_options={
                "clan": "Crane",
                "type": "Personality",
            }
        )
        assert len(cards) > 0
        assert all(c["clan"] == "Crane" and c["type"] == "Personality" for c in cards)

    def test_text_search_with_filters(self):
        """Should combine text search with property filters."""
        cards = query_cards_filtered(text_query="Doji", filter_options={"type": "Personality"})
        assert len(cards) > 0
        for card in cards:
            assert (
                "doji" in card["name"].lower()
                or "doji" in card["id"].lower()
                or (card.get("text") and "doji" in card["text"].lower())
            )
            assert card["type"] == "Personality"

    def test_filter_by_legality(self):
        """Should filter by format legality using subquery."""
        cards = query_cards_filtered(filter_options={"legality": ("Ivory Edition", ["legal"])})
        assert isinstance(cards, list)
        assert all("id" in c for c in cards)

    def test_no_matches_returns_empty_list(self):
        """Should return empty list when no cards match filters."""
        cards = query_cards_filtered(text_query="XYZ_IMPOSSIBLE_MATCH_9999")
        assert cards == []

    def test_none_filter_value_ignored(self):
        """Should ignore filters with None values."""
        all_cards = query_cards_filtered()
        filtered_cards = query_cards_filtered(filter_options={"clan": None})
        assert len(all_cards) == len(filtered_cards)

    def test_results_include_image_path(self):
        """Should include image_path from first print."""
        cards = query_cards_filtered()
        for card in cards[:5]:
            assert "image_path" in card


class TestPagination:
    """Test SQL-level pagination via query_cards_page."""

    def test_returns_tuple(self):
        cards, total = query_cards_page()
        assert isinstance(cards, list)
        assert isinstance(total, int)
        assert total > 0

    def test_default_limit(self):
        cards, total = query_cards_page()
        assert len(cards) <= 100
        assert total >= len(cards)

    def test_custom_limit(self):
        cards, total = query_cards_page(limit=10)
        assert len(cards) == 10
        assert total > 10

    def test_offset_pages_do_not_overlap(self):
        page1, total1 = query_cards_page(limit=5, offset=0)
        page2, total2 = query_cards_page(limit=5, offset=5)
        assert total1 == total2
        ids1 = {c["id"] for c in page1}
        ids2 = {c["id"] for c in page2}
        assert ids1.isdisjoint(ids2)

    def test_offset_beyond_total_returns_empty(self):
        cards, total = query_cards_page(limit=10, offset=999999)
        assert cards == []
        assert total > 0

    def test_filters_reduce_total(self):
        _, all_total = query_cards_page(limit=1)
        _, crane_total = query_cards_page(
            filter_options={"clan": "Crane"},
            limit=1,
        )
        assert 0 < crane_total < all_total

    def test_text_query_with_pagination(self):
        cards, total = query_cards_page(text_query="Doji", limit=5)
        assert total > 0
        assert len(cards) <= 5
        for card in cards:
            combined = (
                card["name"] + " " + card.get("id", "") + " " + (card.get("text") or "")
            ).lower()
            assert "doji" in combined

    def test_no_matches_returns_zero(self):
        cards, total = query_cards_page(text_query="XYZ_IMPOSSIBLE_9999", limit=10)
        assert cards == []
        assert total == 0

    def test_consistent_with_unfiltered(self):
        all_cards = query_cards_filtered()
        _, total = query_cards_page(limit=1)
        assert total == len(all_cards)


class TestCountCardsFiltered:
    """Test count-only query (no data fetch)."""

    def test_count_all(self):
        count = count_cards_filtered()
        all_cards = query_cards_filtered()
        assert count == len(all_cards)

    def test_count_with_filter(self):
        count = count_cards_filtered(filter_options={"clan": "Crane"})
        cards = query_cards_filtered(filter_options={"clan": "Crane"})
        assert count == len(cards)

    def test_count_no_match(self):
        assert count_cards_filtered(text_query="XYZ_IMPOSSIBLE_9999") == 0


class TestRandomCards:
    """Test SQL-level random card sampling."""

    def test_returns_requested_count(self):
        cards = query_random_cards(5)
        assert len(cards) == 5

    def test_cards_have_expected_fields(self):
        cards = query_random_cards(1)
        card = cards[0]
        assert "id" in card
        assert "name" in card
        assert "image_path" in card

    def test_deck_filter(self):
        cards = query_random_cards(10, deck_filter="FATE")
        assert all(c["side"] == "FATE" for c in cards)

    def test_returns_different_results(self):
        ids1 = {c["id"] for c in query_random_cards(20)}
        ids2 = {c["id"] for c in query_random_cards(20)}
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
    assert "DYNASTY" in decks


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


class TestPrivateDsnDetection:
    @pytest.mark.parametrize(
        "dsn, expected_host",
        [
            ("postgresql://localhost/yasuki", "localhost"),
            ("postgresql://user:pass@localhost:5432/yasuki", "localhost"),
            ("postgresql://user:pass@127.0.0.1:5432/yasuki", "127.0.0.1"),
            ("postgresql://user:pass@db:5432/yasuki", "db"),
            ("postgresql://user:pass@my-postgres:5432/yasuki", "my-postgres"),
            ("postgresql://user:pass@10.0.0.5:5432/yasuki", "10.0.0.5"),
            ("postgresql://user:pass@172.18.0.2:5432/yasuki", "172.18.0.2"),
            ("postgresql://user:pass@192.168.1.100:5432/yasuki", "192.168.1.100"),
            (
                "postgresql://user:pass@roundhouse.proxy.rlwy.net:5432/railway",
                "roundhouse.proxy.rlwy.net",
            ),
            ("postgresql://user:pass@db.railway.internal:5432/railway", "db.railway.internal"),
            ("postgresql://user:pass@44.200.1.5:5432/yasuki", "44.200.1.5"),
        ],
        ids=[
            "localhost_no_creds",
            "localhost_with_creds",
            "loopback",
            "docker_service",
            "docker_hyphenated",
            "rfc1918_10",
            "rfc1918_172",
            "rfc1918_192",
            "railway_proxy",
            "railway_internal",
            "public_ip",
        ],
    )
    def test_extract_host(self, dsn, expected_host):
        assert _extract_host(dsn) == expected_host

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
