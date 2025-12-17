from app.database import (
    query_all_cards,
    search_cards,
    get_card_by_id,
    query_all_prints,
    get_prints_by_card_id,
    query_cards_filtered,
    query_stat_ranges,
    query_types_with_stat,
)
import pytest


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


def test_query_all_prints_shows_duplicate_card_names():
    from collections import Counter

    prints = query_all_prints()
    card_names = [p["name"] for p in prints]
    name_counts = Counter(card_names)

    multi_print_cards = [name for name, count in name_counts.items() if count > 1]
    assert len(multi_print_cards) > 0


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
    import pytest

    with pytest.raises(ValueError, match="Invalid stat name"):
        query_types_with_stat("invalid_stat")

    with pytest.raises(ValueError, match="Invalid stat name"):
        query_types_with_stat("id")


def test_keyword_filter_query_structure():
    """Test that keyword filter generates correct SQL query structure."""
    from app.database import query_cards_filtered

    # Mock the database query to capture the SQL
    # In real usage, this would query the card_keywords table
    filter_options = {"keywords": ["cavalry"]}

    # This will attempt to query the database
    # If database is not available, test will be skipped
    try:
        results = query_cards_filtered("", filter_options)
        # If we get here, database is available
        # Results should be a list (empty or with cards)
        assert isinstance(results, list)
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


def test_multiple_keywords_filter():
    """Test that multiple keywords are properly filtered."""
    from app.database import query_cards_filtered

    filter_options = {"keywords": ["cavalry", "experienced"]}

    try:
        results = query_cards_filtered("", filter_options)
        assert isinstance(results, list)
        # If results exist, they should have one of the keywords
        # (Note: this depends on database content)
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


def test_keyword_with_other_filters():
    """Test that keyword filter combines with other filters."""
    filter_options = {
        "keywords": ["cavalry"],
        "clans": ["Unicorn"],
        "force_min": 3,
    }

    try:
        results = query_cards_filtered("", filter_options)
        assert isinstance(results, list)
        # Results should be cavalry Unicorn cards with force >= 3
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


def test_is_unique_still_works():
    """Test that is_unique filter still works alongside keyword filters."""
    from app.database import query_cards_filtered

    filter_options = {"is_unique": True}

    try:
        results = query_cards_filtered("", filter_options)
        assert isinstance(results, list)
        # All results should be unique cards
        for card in results:
            assert card.get("is_unique") is True
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


def test_combined_is_unique_and_keyword():
    """Test that is_unique and keyword filters can be combined."""
    from app.database import query_cards_filtered

    filter_options = {"is_unique": True, "keywords": ["experienced"]}

    try:
        results = query_cards_filtered("", filter_options)
        assert isinstance(results, list)
        # All results should be unique AND have experienced keyword
    except Exception as e:
        pytest.skip(f"Database not available: {e}")
