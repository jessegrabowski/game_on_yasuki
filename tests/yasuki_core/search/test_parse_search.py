import pytest

from yasuki_core.search import (
    tokenize_query,
    parse_token,
    parse_search_query,
    build_filter_options,
    parse_and_build_query,
    SearchTerm,
    ParsedQuery,
    normalize_field_name,
)


class TestFieldNormalization:
    def test_normalize_aliases(self):
        assert normalize_field_name("o") == "text"
        assert normalize_field_name("oracle") == "text"
        assert normalize_field_name("t") == "type"
        assert normalize_field_name("c") == "clan"
        assert normalize_field_name("s") == "set"
        assert normalize_field_name("f") == "force"
        assert normalize_field_name("format") == "format"
        assert normalize_field_name("r") == "rarity"
        assert normalize_field_name("side") == "deck"
        assert normalize_field_name("gold") == "gold_cost"
        assert normalize_field_name("ph") == "personal_honor"
        assert normalize_field_name("hr") == "honor_requirement"
        assert normalize_field_name("province") == "province_strength"

    def test_normalize_stat_abbreviations(self):
        assert normalize_field_name("gc") == "gold_cost"
        assert normalize_field_name("gp") == "gold_production"
        assert normalize_field_name("fc") == "focus"
        assert normalize_field_name("ch") == "chi"
        assert normalize_field_name("ps") == "province_strength"
        assert normalize_field_name("sh") == "starting_honor"
        assert normalize_field_name("fh") == "starting_honor"
        assert normalize_field_name("exp") == "experience"
        assert normalize_field_name("xp") == "experience"

    def test_normalize_case_insensitive(self):
        assert normalize_field_name("FORCE") == "force"
        assert normalize_field_name("Force") == "force"
        assert normalize_field_name("TYPE") == "type"


class TestTokenization:
    def test_simple_tokens(self):
        tokens = tokenize_query("name:Doji type:personality")
        assert tokens == ["name:Doji", "type:personality"]

    def test_quoted_strings(self):
        tokens = tokenize_query('"Doji Hoturi" force>3')
        assert tokens == ['"Doji Hoturi"', "force>3"]

    def test_quoted_with_spaces(self):
        tokens = tokenize_query('name:"Doji Hoturi" clan:Crane')
        assert tokens == ['name:"Doji Hoturi"', "clan:Crane"]

    def test_multiple_spaces(self):
        tokens = tokenize_query("clan:Crane  type:personality")
        assert tokens == ["clan:Crane", "type:personality"]

    def test_empty_query(self):
        tokens = tokenize_query("")
        assert tokens == []


class TestTokenParsing:
    def test_field_colon_value(self):
        term = parse_token("name:Doji")
        assert term.field == "name"
        assert term.operator == ":"
        assert term.value == "Doji"
        assert term.negated is False

    def test_numeric_comparison_greater(self):
        term = parse_token("force>3")
        assert term.field == "force"
        assert term.operator == ">"
        assert term.value == "3"

    def test_numeric_comparison_greater_equal(self):
        term = parse_token("chi>=2")
        assert term.field == "chi"
        assert term.operator == ">="
        assert term.value == "2"

    def test_numeric_comparison_less(self):
        term = parse_token("focus<5")
        assert term.field == "focus"
        assert term.operator == "<"
        assert term.value == "5"

    def test_numeric_comparison_less_equal(self):
        term = parse_token("gold_cost<=3")
        assert term.field == "gold_cost"
        assert term.operator == "<="
        assert term.value == "3"

    def test_negation(self):
        term = parse_token("-type:event")
        assert term.field == "type"
        assert term.operator == ":"
        assert term.value == "event"
        assert term.negated is True

    def test_bare_quoted_phrase_is_substring(self):
        # A bare "phrase" searches as a substring (operator ":"), the same broad match a plain word
        # gets. Only !"phrase" is exact.
        term = parse_token('"Doji Hoturi"')
        assert term.field is None
        assert term.operator == ":"
        assert term.value == "Doji Hoturi"

    def test_exact_match_with_exclamation(self):
        term = parse_token('!"exact phrase"')
        assert term.field is None
        assert term.operator == "="
        assert term.value == "exact phrase"

    def test_negated_exact_match(self):
        term = parse_token('-!"Doji Hoturi"')
        assert term.field is None
        assert term.operator == "="
        assert term.value == "Doji Hoturi"
        assert term.negated is True

    def test_plain_text(self):
        term = parse_token("Crane")
        assert term.field is None
        assert term.operator == ":"
        assert term.value == "Crane"

    def test_is_unique(self):
        term = parse_token("is:unique")
        assert term.field == "is"
        assert term.operator == ":"
        assert term.value == "unique"

    def test_field_alias(self):
        term = parse_token("t:personality")
        assert term.field == "type"
        assert term.value == "personality"


class TestQueryParsing:
    def test_single_term(self):
        parsed = parse_search_query("name:Doji")
        assert len(parsed.terms) == 1
        assert parsed.terms[0].field == "name"
        assert parsed.terms[0].value == "Doji"

    def test_multiple_terms(self):
        parsed = parse_search_query("name:Doji type:personality")
        assert len(parsed.terms) == 2

    def test_and_keyword_is_stripped(self):
        parsed = parse_search_query("name:Doji AND type:personality")
        assert len(parsed.terms) == 2

    def test_or_keyword_is_stripped(self):
        # This flat parser drops OR; the boolean AST (boolean_query) is what honors real OR.
        parsed = parse_search_query("clan:Crane OR clan:Lion")
        assert len(parsed.terms) == 2

    def test_keywords_stripped_when_mixed_with_or(self):
        # Regression: the old OR-splitting path left AND/NOT as bogus text terms.
        parsed = parse_search_query("clan:Crane OR type:personality AND is:unique")
        assert [term.field for term in parsed.terms] == ["clan", "type", "is"]

    def test_mixed_terms(self):
        parsed = parse_search_query('name:Doji force>3 "Crane Clan"')
        assert len(parsed.terms) == 3
        assert parsed.terms[0].field == "name"
        assert parsed.terms[1].field == "force"
        assert parsed.terms[2].field is None
        assert parsed.terms[2].value == "Crane Clan"

    def test_empty_query(self):
        parsed = parse_search_query("")
        assert len(parsed.terms) == 0

    def test_negated_terms(self):
        parsed = parse_search_query("clan:Crane -type:event")
        assert len(parsed.terms) == 2
        assert parsed.terms[0].negated is False
        assert parsed.terms[1].negated is True


class TestFilterBuilding:
    def test_text_search(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field=None, operator=":", value="Doji", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert "Doji" in text_query
        assert len(filters) == 0

    def test_exact_match_emits_name_exact(self):
        _, filters = parse_and_build_query('!"Doji Hoturi"')
        assert filters["name_exact"] == ["Doji Hoturi"]
        assert "name_contains" not in filters

    def test_negated_exact_match_emits_name_exact_excludes(self):
        _, filters = parse_and_build_query('-!"Doji Hoturi"')
        assert filters["name_exact_excludes"] == ["Doji Hoturi"]

    def test_negated_bare_word_emits_bare_excludes(self):
        text, filters = parse_and_build_query("-doji")
        assert text == ""
        assert filters["bare_excludes"] == ["doji"]

    def test_bare_word_mixes_include_and_exclude(self):
        text, filters = parse_and_build_query("crane -bushi")
        assert text == "crane"
        assert filters["bare_excludes"] == ["bushi"]

    def test_stray_dash_carries_no_exclude(self):
        # A trailing '-' (or bare '""') has no needle; it must not become a match-everything
        # exclude that blanks the results. Regression for the empty-bare-word bug.
        text, filters = parse_and_build_query("crane -")
        assert text == "crane"
        assert "bare_excludes" not in filters

    def test_name_search(self):
        # name: scopes to the card name only, not the broad name+text query.
        parsed = ParsedQuery(
            terms=[SearchTerm(field="name", operator=":", value="Hoturi", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert text_query == ""
        assert filters["name_contains"] == ["Hoturi"]

    def test_clan_filter(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="clan", operator=":", value="Crane", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["clans"] == ["Crane"]

    def test_type_filter(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="type", operator=":", value="personality", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["types"] == ["personality"]

    def test_deck_filter(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="deck", operator=":", value="fate", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["decks"] == ["FATE"]

    # Each categorical field negates into a <key>_excludes list, applying the same case transform as
    # its positive filter (deck upper, type lower, clan/rarity verbatim).
    @pytest.mark.parametrize(
        "query, key, expected",
        [
            ("-deck:fate", "decks_excludes", ["FATE"]),
            ("-type:Sensei", "types_excludes", ["sensei"]),
            ("-c:Crane", "clans_excludes", ["Crane"]),
            ("-rarity:rare", "rarities_excludes", ["rare"]),
        ],
    )
    def test_categorical_negation_emits_excludes(self, query, key, expected):
        _, filters = parse_and_build_query(query)
        assert filters[key] == expected
        assert key.removesuffix("_excludes") not in filters

    def test_categorical_mixes_include_and_exclude(self):
        # c:crane -t:sensei: keep the positive clan, forbid the negated type in one query.
        _, filters = parse_and_build_query("c:crane -t:sensei")
        assert filters["clans"] == ["crane"]
        assert filters["types_excludes"] == ["sensei"]

    def test_same_field_include_and_exclude_coexist(self):
        _, filters = parse_and_build_query("type:personality -type:sensei")
        assert filters["types"] == ["personality"]
        assert filters["types_excludes"] == ["sensei"]

    def test_artist_negation_emits_excludes(self):
        _, filters = parse_and_build_query("-artist:Hara")
        assert filters["artist_excludes"] == ["Hara"]
        assert "artist" not in filters

    # The parser emits format terms verbatim as (operator, value) specs; resolving aliases and
    # timeline inequalities happens in SQL (see the DB-backed tests in test_api_contract.py).
    def test_format_exact_emits_spec(self):
        _, filters = parse_and_build_query("format:diamond")
        assert filters["format_filters"] == [(":", "diamond")]

    def test_format_inequality_emits_operator(self):
        _, filters = parse_and_build_query("format>diamond")
        assert filters["format_filters"] == [(">", "diamond")]

    def test_format_quoted_full_name_strips_quotes(self):
        _, filters = parse_and_build_query('format:"Rain of Blood (Diamond)"')
        assert filters["format_filters"] == [(":", "Rain of Blood (Diamond)")]

    def test_format_multiple_terms_kept_in_order(self):
        _, filters = parse_and_build_query("format>diamond format<emperor")
        assert filters["format_filters"] == [(">", "diamond"), ("<", "emperor")]

    def test_format_negation_emits_excludes(self):
        # Strict set complement: forbid membership, keep the operator verbatim (resolved in SQL).
        _, filters = parse_and_build_query("-format>=diamond")
        assert filters["format_filters_excludes"] == [(">=", "diamond")]
        assert "format_filters" not in filters

    def test_format_include_and_exclude_coexist(self):
        _, filters = parse_and_build_query("format:diamond -format:emperor")
        assert filters["format_filters"] == [(":", "diamond")]
        assert filters["format_filters_excludes"] == [(":", "emperor")]

    def test_set_negation_emits_excludes(self):
        _, filters = parse_and_build_query("-set>=GE")
        assert filters["set_filters_excludes"] == [(">=", "GE")]
        assert "set_filters" not in filters

    # `set` terms emit the same (operator, value) specs; resolution by name/code and release-date
    # inequalities happen in SQL.
    def test_set_exact_emits_spec(self):
        _, filters = parse_and_build_query("set:GE")
        assert filters["set_filters"] == [(":", "GE")]

    def test_set_inequality_emits_operator(self):
        _, filters = parse_and_build_query("set>=GE")
        assert filters["set_filters"] == [(">=", "GE")]

    def test_set_quoted_full_name(self):
        _, filters = parse_and_build_query('set:"Gold Edition"')
        assert filters["set_filters"] == [(":", "Gold Edition")]

    def test_set_two_sided_range(self):
        _, filters = parse_and_build_query("set>=GE set<=DE")
        assert filters["set_filters"] == [(">=", "GE"), ("<=", "DE")]

    def test_title_aliases_to_name(self):
        _, filters = parse_and_build_query("title:hida")
        assert filters["name_contains"] == ["hida"]

    def test_arc_aliases_to_format(self):
        _, filters = parse_and_build_query("arc:lotus")
        assert filters["format_filters"] == [(":", "lotus")]

    def test_unknown_field_is_unsatisfiable(self):
        # An unrecognised field must NOT be silently text-searched (that returned nonsense, e.g.
        # gc>5 matching cards containing "5"); the query becomes unsatisfiable instead.
        text, filters = parse_and_build_query("bogusfield:scorpion")
        assert text == ""
        assert filters["_unknown_fields"] == ["bogusfield"]

    def test_include_tokens(self):
        _, filters = parse_and_build_query("include:tokens")
        assert filters["include"] == {"tokens"}

    def test_include_unknown_category_ignored(self):
        _, filters = parse_and_build_query("include:bogus")
        assert "include" not in filters

    def test_artist_alias_and_field(self):
        _, by_alias = parse_and_build_query("a:Hara")
        _, by_name = parse_and_build_query("artist:Hara")
        assert by_alias["artist"] == ["Hara"] == by_name["artist"]

    def test_flavor_alias_strips_quotes(self):
        _, filters = parse_and_build_query('ft:"a moment of honor"')
        assert filters["flavor"] == ["a moment of honor"]

    def test_story_field(self):
        _, filters = parse_and_build_query('story:"Paul Ashman"')
        assert filters["story"] == ["Paul Ashman"]

    def test_quoted_field_value_strips_quotes(self):
        # A quoted phrase on a text/name field searches as the phrase, scoped to that field.
        _, filters = parse_and_build_query('o:"take control"')
        assert filters["rules_text_contains"] == ["take control"]
        _, filters = parse_and_build_query('name:"Doji Hoturi"')
        assert filters["name_contains"] == ["Doji Hoturi"]

    def test_dash_stat_matches_null(self):
        # `hr:-` finds cards with no honor requirement (the dash stat), distinct from hr:0.
        _, filters = parse_and_build_query("hr:-")
        assert filters["honor_requirement"] == "isnull"
        _, zero = parse_and_build_query("hr:0")
        assert zero["honor_requirement"] == (0, 0)

    def test_negated_dash_stat_matches_non_null(self):
        _, filters = parse_and_build_query("-f:-")
        assert filters["force"] == "notnull"

    def test_experience_is_a_numeric_field(self):
        # exp:/experience: pin the version rank; negatives (Inexperienced) are ordinary values.
        _, base = parse_and_build_query("exp:0")
        assert base["experience"] == (0, 0)
        _, experienced = parse_and_build_query("experience>=1")
        assert experienced["experience"] == (1, None)
        _, inexperienced = parse_and_build_query("xp:-1")
        assert inexperienced["experience"] == (-1, -1)

    def test_is_banned(self):
        _, filters = parse_and_build_query("is:banned")
        assert filters["is_banned"] is True
        _, negated = parse_and_build_query("-is:banned")
        assert negated["is_banned"] is False

    def test_is_unique(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="is", operator=":", value="unique", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["is_unique"] is True

    def test_is_not_unique(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="is", operator=":", value="unique", negated=True)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["is_unique"] is False

    def test_is_keyword(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="is", operator=":", value="cavalry", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["keywords"] == ["cavalry"]

    def test_is_multiple_keywords(self):
        parsed = ParsedQuery(
            terms=[
                SearchTerm(field="is", operator=":", value="cavalry", negated=False),
                SearchTerm(field="is", operator=":", value="experienced", negated=False),
            ]
        )
        text_query, filters = build_filter_options(parsed)
        assert "cavalry" in filters["keywords"]
        assert "experienced" in filters["keywords"]

    def test_is_kenshi(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="is", operator=":", value="kenshi", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["keywords"] == ["kenshi"]

    def test_has_keyword(self):
        text, filters = parse_and_build_query("has:cavalry")
        assert filters["keywords"] == ["cavalry"]

    def test_has_unique(self):
        text, filters = parse_and_build_query("has:unique")
        assert filters["is_unique"] is True

    def test_has_multiple_keywords(self):
        text, filters = parse_and_build_query("has:cavalry has:experienced")
        assert "cavalry" in filters["keywords"]
        assert "experienced" in filters["keywords"]

    def test_multiple_keywords_and_logic(self):
        """Test that multiple keywords use AND logic (must have all)."""
        text, filters = parse_and_build_query("is:shugenja is:shadowlands")
        assert filters["keywords"] == ["shugenja", "shadowlands"]

    def test_three_keywords_and_logic(self):
        """Test three keywords with AND logic."""
        text, filters = parse_and_build_query("is:cavalry is:experienced is:unique")
        assert "cavalry" in filters["keywords"]
        assert "experienced" in filters["keywords"]
        # Note: is:unique is special and goes to is_unique field
        assert filters.get("is_unique") is True

    def test_numeric_equal(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="force", operator=":", value="3", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["force"] == (3, 3)

    def test_numeric_greater_than(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="force", operator=">", value="3", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["force"] == (4, None)

    def test_numeric_greater_equal(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="chi", operator=">=", value="2", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["chi"] == (2, None)

    def test_numeric_less_than(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="focus", operator="<", value="5", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["focus"] == (None, 4)

    def test_numeric_less_equal(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="gold_cost", operator="<=", value="3", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["gold_cost"] == (None, 3)

    def test_format_filter(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="format", operator=":", value="Ivory Edition", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["format_filters"] == [(":", "Ivory Edition")]

    def test_combined_filters(self):
        parsed = ParsedQuery(
            terms=[
                SearchTerm(field="name", operator=":", value="Doji", negated=False),
                SearchTerm(field="clan", operator=":", value="Crane", negated=False),
                SearchTerm(field="force", operator=">", value="3", negated=False),
            ]
        )
        text_query, filters = build_filter_options(parsed)
        assert filters["name_contains"] == ["Doji"]
        assert filters["clans"] == ["Crane"]
        assert filters["force"] == (4, None)


class TestEndToEnd:
    def test_simple_name_search(self):
        text, filters = parse_and_build_query("Doji")
        assert "Doji" in text

    def test_text_search(self):
        _, filters = parse_and_build_query("text:battle")
        assert filters["rules_text_contains"] == ["battle"]

    def test_oracle_search(self):
        _, filters = parse_and_build_query("o:honor")
        assert filters["rules_text_contains"] == ["honor"]

    def test_field_specific_search(self):
        text, filters = parse_and_build_query("clan:Crane type:personality")
        assert filters["clans"] == ["Crane"]
        assert filters["types"] == ["personality"]

    def test_numeric_search(self):
        text, filters = parse_and_build_query("force>=3 chi<2")
        assert filters["force"] == (3, None)
        assert filters["chi"] == (None, 1)

    def test_complex_query(self):
        text, filters = parse_and_build_query("name:Doji clan:Crane force>3 is:unique")
        assert filters["name_contains"] == ["Doji"]
        assert filters["clans"] == ["Crane"]
        assert filters["force"] == (4, None)
        assert filters["is_unique"] is True

    def test_quoted_search(self):
        text, filters = parse_and_build_query('"Doji Hoturi"')
        assert "Doji Hoturi" in text

    def test_negated_search(self):
        text, filters = parse_and_build_query("clan:Crane -type:event")
        assert filters["clans"] == ["Crane"]

    def test_alias_usage(self):
        text, filters = parse_and_build_query("t:personality c:Crane f>3")
        assert filters["types"] == ["personality"]
        assert filters["clans"] == ["Crane"]
        assert filters["force"] == (4, None)

    def test_deck_side_alias(self):
        text, filters = parse_and_build_query("side:fate")
        assert filters["decks"] == ["FATE"]

    def test_gold_alias(self):
        text, filters = parse_and_build_query("gold<=3")
        assert filters["gold_cost"] == (None, 3)

    def test_keyword_search(self):
        text, filters = parse_and_build_query("is:cavalry")
        assert filters["keywords"] == ["cavalry"]

    def test_multiple_keyword_search(self):
        text, filters = parse_and_build_query("is:cavalry is:experienced")
        assert "cavalry" in filters["keywords"]
        assert "experienced" in filters["keywords"]

    def test_keyword_with_other_filters(self):
        text, filters = parse_and_build_query("is:cavalry clan:Unicorn force>3")
        assert filters["keywords"] == ["cavalry"]
        assert filters["clans"] == ["Unicorn"]
        assert filters["force"] == (4, None)

    def test_blank_search_defaults_to_all_predicate(self):
        text, filters = parse_and_build_query("   ")
        assert text == ""
        assert filters == {"all": True}

    def test_all_predicate_is_recognized(self):
        # all: is a real predicate, not an unknown field — no _unknown_fields, no nonsense.
        _, filters = parse_and_build_query("all:cards")
        assert filters == {"all": True}

    def test_name_scopes_to_name_not_rules_text(self):
        _, filters = parse_and_build_query("name:caravan")
        assert filters == {"name_contains": ["caravan"]}

    def test_oracle_scopes_to_rules_text_not_name(self):
        _, filters = parse_and_build_query("o:caravan")
        assert filters == {"rules_text_contains": ["caravan"]}

    def test_negated_oracle_excludes_rules_text(self):
        _, filters = parse_and_build_query("-o:bow")
        assert filters == {"rules_text_excludes": ["bow"]}

    def test_unknown_stat_inequality_is_unsatisfiable(self):
        # The reported bug: an unknown field inequality used to dump the value into a text search
        # (xyz>5 matching cards containing "5"); it must become unsatisfiable instead.
        text, filters = parse_and_build_query("xyz>5")
        assert text == ""
        assert filters["_unknown_fields"] == ["xyz"]

    def test_stat_abbreviation_inequality(self):
        # gc is now a real alias for gold_cost, so gc>5 is a proper numeric filter, not unknown.
        text, filters = parse_and_build_query("gc>5")
        assert text == ""
        assert filters["gold_cost"] == (6, None)
