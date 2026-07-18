from yasuki_core.database import _build_card_filter

# _build_card_filter is a pure (clause, params) builder — no database needed — so these run
# everywhere, unlike the DB-backed tests in test_database.py.

_PRINT_EXISTS = "EXISTS (SELECT 1 FROM prints p WHERE p.card_id = c.card_id"


def test_bare_text_query_reaches_per_print_rules_text():
    clause, params = _build_card_filter(text_query="destroy")
    assert _PRINT_EXISTS in clause
    assert clause.count("p.rules_text ILIKE") == 1
    # name, card_id, card rules_text, and the per-print rules_text all take the same pattern.
    assert params == ["%destroy%"] * 4


def test_rules_text_contains_ors_in_per_print():
    clause, params = _build_card_filter(filter_options={"rules_text_contains": ["bow"]})
    assert f" OR {_PRINT_EXISTS}" in clause
    assert params == ["%bow%", "%bow%"]


def test_rules_text_excludes_negates_card_and_per_print():
    # Excluding a phrase must hide a card whose *current* text or *any printing's* wording matches,
    # so the disjunction is negated as a whole (De Morgan).
    clause, params = _build_card_filter(filter_options={"rules_text_excludes": ["bow"]})
    assert "NOT ILIKE" in clause
    assert f"AND NOT {_PRINT_EXISTS}" in clause
    assert params == ["%bow%", "%bow%"]


def test_name_search_stays_single_column():
    clause, params = _build_card_filter(filter_options={"name_contains": ["kachiko"]})
    assert "c.name ILIKE" in clause
    assert "prints" not in clause
    assert params == ["%kachiko%"]


def test_like_wildcards_in_needle_are_escaped():
    _, params = _build_card_filter(text_query="50%")
    assert params == ["%50\\%%"] * 4
