from app.gui.ui.deck_builder.parse_search import (
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
        assert normalize_field_name("province") == "province_strength"

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

    def test_quoted_exact_match(self):
        term = parse_token('"Doji Hoturi"')
        assert term.field is None
        assert term.operator == "="
        assert term.value == "Doji Hoturi"

    def test_exact_match_with_exclamation(self):
        term = parse_token('!"exact phrase"')
        assert term.field is None
        assert term.operator == "="
        assert term.value == "exact phrase"

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
        assert parsed.logic == "AND"
        assert parsed.terms[0].field == "name"
        assert parsed.terms[0].value == "Doji"

    def test_multiple_terms_implicit_and(self):
        parsed = parse_search_query("name:Doji type:personality")
        assert len(parsed.terms) == 2
        assert parsed.logic == "AND"

    def test_explicit_and(self):
        parsed = parse_search_query("name:Doji AND type:personality")
        assert len(parsed.terms) == 2
        assert parsed.logic == "AND"

    def test_or_logic(self):
        parsed = parse_search_query("clan:Crane OR clan:Lion")
        assert len(parsed.terms) == 2
        assert parsed.logic == "OR"

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
        assert parsed.logic == "AND"

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

    def test_name_search(self):
        parsed = ParsedQuery(
            terms=[SearchTerm(field="name", operator=":", value="Hoturi", negated=False)]
        )
        text_query, filters = build_filter_options(parsed)
        assert "Hoturi" in text_query

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
        assert filters["legality"] == ("Ivory Edition", ["legal"])

    def test_combined_filters(self):
        parsed = ParsedQuery(
            terms=[
                SearchTerm(field="name", operator=":", value="Doji", negated=False),
                SearchTerm(field="clan", operator=":", value="Crane", negated=False),
                SearchTerm(field="force", operator=">", value="3", negated=False),
            ]
        )
        text_query, filters = build_filter_options(parsed)
        assert "Doji" in text_query
        assert filters["clans"] == ["Crane"]
        assert filters["force"] == (4, None)


class TestEndToEnd:
    def test_simple_name_search(self):
        text, filters = parse_and_build_query("Doji")
        assert "Doji" in text

    def test_text_search(self):
        text, filters = parse_and_build_query("text:battle")
        assert "battle" in text

    def test_oracle_search(self):
        text, filters = parse_and_build_query("o:honor")
        assert "honor" in text

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
        assert "Doji" in text
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
