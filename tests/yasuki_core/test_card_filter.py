from yasuki_core.database import (
    _build_card_filter,
    build_search_filters,
    compile_query,
    compile_term,
)
from yasuki_core.search.boolean_query import parse_query
from yasuki_core.search.parse_search import parse_token

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


def test_year_filter_extracts_release_year():
    exact, params = _build_card_filter(filter_options={"year_filters": [(":", 2005)]})
    assert "EXTRACT(YEAR FROM s.release_date) = %s" in exact
    assert params == [2005]
    ge, _ = _build_card_filter(filter_options={"year_filters": [(">=", 2010)]})
    assert "EXTRACT(YEAR FROM s.release_date) >= %s" in ge


def test_presence_flags_are_null_checks():
    flip, _ = _build_card_filter(filter_options={"is_flip": True})
    assert "c.back_card_id IS NOT NULL" in flip
    not_flip, _ = _build_card_filter(filter_options={"is_flip": False})
    assert "c.back_card_id IS NULL" in not_flip
    errata, _ = _build_card_filter(filter_options={"has_errata": True})
    assert "c.errata_text IS NOT NULL" in errata


def test_name_exact_matches_whole_name_case_insensitively():
    clause, params = _build_card_filter(filter_options={"name_exact": ["Doji Hoturi"]})
    assert "lower(c.name) = lower(%s)" in clause
    assert params == ["Doji Hoturi"]


def test_name_exact_excludes_negates_the_equality():
    clause, params = _build_card_filter(filter_options={"name_exact_excludes": ["Doji Hoturi"]})
    assert "lower(c.name) != lower(%s)" in clause
    assert params == ["Doji Hoturi"]


def test_bare_excludes_negates_the_broad_union():
    clause, params = _build_card_filter(filter_options={"bare_excludes": ["doji"]})
    assert "NOT (c.name ILIKE" in clause
    assert _PRINT_EXISTS in clause
    assert params == ["%doji%"] * 4


def test_like_wildcards_in_needle_are_escaped():
    _, params = _build_card_filter(text_query="50%")
    assert params == ["%50\\%%"] * 4


def test_types_excludes_negates_membership():
    clause, params = _build_card_filter(filter_options={"types_excludes": ["sensei"]})
    assert "c.card_id NOT IN (SELECT card_id FROM card_card_types" in clause
    assert params == [["Sensei"]]


def test_clans_excludes_negates_membership_including_all_clans_marker():
    # -clan:crane is the complement of clan:crane, so the "All Clans" sensei marker is excluded too.
    clause, params = _build_card_filter(filter_options={"clans_excludes": ["crane"]})
    assert "c.card_id NOT IN (SELECT card_id FROM card_clans" in clause
    assert set(params[0]) == {"crane", "all clans"}


def test_include_and_exclude_type_both_emit_conditions():
    clause, _ = _build_card_filter(
        filter_options={"types": ["personality"], "types_excludes": ["sensei"]}
    )
    assert "c.card_id IN (SELECT card_id FROM card_card_types" in clause
    assert "c.card_id NOT IN (SELECT card_id FROM card_card_types" in clause


def test_story_excludes_keeps_null_credits():
    clause, params = _build_card_filter(filter_options={"story_excludes": ["Ashman"]})
    assert "c.story IS NULL OR c.story NOT ILIKE" in clause
    assert params == ["%Ashman%"]


def test_format_excludes_negates_membership_not_the_operator():
    # -format>=diamond is the strict complement: NOT IN the set of cards legal at/after the ref,
    # with the >= kept verbatim inside the subquery (not flipped to <).
    clause, _ = _build_card_filter(filter_options={"format_filters_excludes": [(">=", "diamond")]})
    assert "c.card_id NOT IN (SELECT cl.card_id FROM card_legalities" in clause
    assert "f.legal_from >=" in clause


def test_format_excludes_fails_closed_on_unresolvable_reference():
    # A typo'd -format:xyz must match nothing, not everything, so the NOT IN is guarded by an
    # EXISTS that the unresolved reference fails.
    clause, _ = _build_card_filter(filter_options={"format_filters_excludes": [(":", "xyz")]})
    assert "EXISTS (SELECT 1 FROM formats" in clause
    assert "AND c.card_id NOT IN" in clause


def test_set_excludes_negates_membership_and_fails_closed():
    clause, _ = _build_card_filter(filter_options={"set_filters_excludes": [(">=", "GE")]})
    assert "EXISTS (SELECT 1 FROM l5r_sets" in clause
    assert "AND c.card_id NOT IN (SELECT p.card_id FROM prints p" in clause
    assert "s.release_date >=" in clause


# compile_term maps one search term to one predicate by reusing the same per-field SQL as
# _build_card_filter, so the field-specific shape is covered above; these pin its composition rules.
def test_compile_term_returns_a_single_condition_bare():
    sql, params = compile_term(parse_token("c:crane"))
    assert sql == "c.card_id IN (SELECT card_id FROM card_clans WHERE lower(clan) = ANY(%s))"
    assert set(params[0]) == {"crane", "all clans"}


def test_compile_term_bare_word_uses_the_broad_union():
    sql, params = compile_term(parse_token("crane"))
    assert sql.startswith("(c.name ILIKE")
    assert _PRINT_EXISTS in sql
    assert params == ["%crane%"] * 4


def test_compile_term_ands_a_multi_condition_term():
    # is:a&b compiles to both keyword predicates ANDed into one parenthesized expression, with
    # params in placeholder order.
    sql, params = compile_term(parse_token("is:cavalry&kensai"))
    assert sql.startswith("(") and sql.endswith(")")
    assert " AND " in sql
    assert sql.count("card_keywords") == 2
    assert params == ["cavalry", "kensai"]


def test_compile_term_without_constraints_is_none():
    assert compile_term(parse_token("all:cards")) is None


def test_compile_term_negation_reuses_the_exclude_sql():
    sql, _ = compile_term(parse_token("-t:sensei"))
    assert "c.card_id NOT IN (SELECT card_id FROM card_card_types" in sql


# compile_query recurses the AST into nested SQL; build_search_filters wraps it for the query layer.
def test_compile_query_none_is_none():
    assert compile_query(None) is None


def test_compile_query_or_group_joins_with_or():
    sql, _ = compile_query(parse_query("c:crane OR c:lion"))
    assert sql.startswith("(") and sql.endswith(")")
    assert " OR " in sql


def test_compile_query_and_group_joins_with_and():
    sql, _ = compile_query(parse_query("c:crane t:personality"))
    assert " AND " in sql


def test_compile_query_not_prefixes_the_group():
    sql, _ = compile_query(parse_query("-(c:crane OR c:lion)"))
    assert sql.startswith("NOT (")


def test_compile_query_drops_no_constraint_children():
    # include: is a directive, not a predicate, so it leaves no trace (and no stray TRUE) in the SQL.
    sql, _ = compile_query(parse_query("c:crane include:tokens"))
    assert "card_clans" in sql
    assert "TRUE" not in sql and "include" not in sql


def test_build_search_filters_emits_predicate_and_directives():
    options = build_search_filters("format:shattered include:tokens c:crane")
    assert "_search_ast" in options
    assert options["_active_format"] == "shattered"
    assert options["include"] == {"tokens"}


def test_build_search_filters_empty_query_is_empty():
    assert build_search_filters("") == {}
