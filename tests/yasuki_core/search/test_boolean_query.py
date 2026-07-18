from yasuki_core.search.boolean_query import (
    BoolGroup,
    Not,
    Term,
    active_format_from_ast,
    includes_from_ast,
    parse_query,
    tokenize_boolean,
)
from yasuki_core.search.parse_search import parse_token


def leaf(token: str) -> Term:
    """A Term leaf built from the same token parser the AST uses, for readable expected trees."""
    return Term(parse_token(token))


class TestTokenizeBoolean:
    def test_plain_terms_match_whitespace_split(self):
        assert tokenize_boolean("name:Doji type:personality") == ["name:Doji", "type:personality"]

    def test_parens_are_standalone_tokens(self):
        assert tokenize_boolean("(c:dragon OR c:phoenix)") == [
            "(",
            "c:dragon",
            "OR",
            "c:phoenix",
            ")",
        ]

    def test_paren_flush_against_term_splits(self):
        assert tokenize_boolean("name:Experienced (c:Dragon OR c:Phoenix)") == [
            "name:Experienced",
            "(",
            "c:Dragon",
            "OR",
            "c:Phoenix",
            ")",
        ]

    def test_parens_inside_quotes_stay_literal(self):
        assert tokenize_boolean('o:"Rain of Blood (Diamond)"') == ['o:"Rain of Blood (Diamond)"']

    def test_leading_dash_splits_from_group(self):
        # Group negation tokenizes as a bare '-' before '('; the parser assigns the meaning later.
        assert tokenize_boolean("-(c:crane)") == ["-", "(", "c:crane", ")"]

    def test_nested_parens(self):
        assert tokenize_boolean("((a OR b) c)") == ["(", "(", "a", "OR", "b", ")", "c", ")"]

    def test_unterminated_quote_swallows_rest_including_parens(self):
        # An unclosed quote (user mid-typing) consumes the remainder as one literal token, so a '('
        # after it stays literal rather than splitting.
        assert tokenize_boolean('c:crane "(unclosed') == ["c:crane", '"(unclosed']

    def test_empty_query_yields_no_tokens(self):
        assert tokenize_boolean("") == []
        assert tokenize_boolean("   ") == []


class TestParseQuery:
    def test_single_term_is_a_bare_leaf(self):
        assert parse_query("c:crane") == leaf("c:crane")

    def test_juxtaposition_is_and(self):
        # SIGN-OFF A: space-separated terms AND together.
        assert parse_query("c:crane t:personality") == BoolGroup(
            "AND", [leaf("c:crane"), leaf("t:personality")]
        )

    def test_explicit_and_keyword_matches_juxtaposition(self):
        assert parse_query("c:crane AND t:personality") == parse_query("c:crane t:personality")

    def test_or_combines_alternatives(self):
        assert parse_query("c:crane OR c:lion") == BoolGroup(
            "OR", [leaf("c:crane"), leaf("c:lion")]
        )

    def test_or_binds_looser_than_and(self):
        assert parse_query("a OR b c") == BoolGroup(
            "OR", [leaf("a"), BoolGroup("AND", [leaf("b"), leaf("c")])]
        )

    def test_parens_override_precedence(self):
        assert parse_query("(a OR b) c") == BoolGroup(
            "AND", [BoolGroup("OR", [leaf("a"), leaf("b")]), leaf("c")]
        )

    def test_motivating_query_nests_correctly(self):
        assert parse_query("(c:crane is:courtier) OR (c:lion is:bushi)") == BoolGroup(
            "OR",
            [
                BoolGroup("AND", [leaf("c:crane"), leaf("is:courtier")]),
                BoolGroup("AND", [leaf("c:lion"), leaf("is:bushi")]),
            ],
        )

    def test_group_negation_wraps_in_not(self):
        assert parse_query("-(c:crane)") == Not(leaf("c:crane"))

    def test_group_negation_wraps_a_multi_child_group(self):
        assert parse_query("-(c:crane OR c:lion)") == Not(
            BoolGroup("OR", [leaf("c:crane"), leaf("c:lion")])
        )

    def test_or_keyword_is_case_insensitive(self):
        assert parse_query("a or b") == parse_query("a OR b")

    def test_quotes_escape_the_or_keyword(self):
        # A quoted "or" is a search term, not the operator — the only way to search the literal word.
        assert parse_query('a "or" b') == BoolGroup("AND", [leaf("a"), leaf('"or"'), leaf("b")])


class TestActiveFormatFromAst:
    def test_single_exact_format_is_pinned(self):
        assert active_format_from_ast(parse_query("format:shattered t:personality")) == "shattered"

    def test_or_makes_it_ambiguous(self):
        assert active_format_from_ast(parse_query("format:shattered OR format:ivory")) is None

    def test_two_pinned_formats_are_ambiguous(self):
        assert active_format_from_ast(parse_query("format:shattered format:ivory")) is None

    def test_format_under_group_negation_is_not_pinned(self):
        assert active_format_from_ast(parse_query("-(format:shattered t:personality)")) is None

    def test_negated_format_is_not_pinned(self):
        assert active_format_from_ast(parse_query("-format:shattered")) is None

    def test_inequality_is_not_pinned(self):
        assert active_format_from_ast(parse_query("format>=diamond")) is None

    def test_no_format_is_none(self):
        assert active_format_from_ast(parse_query("c:crane")) is None


class TestIncludesFromAst:
    def test_collects_tokens_alongside_other_terms(self):
        assert includes_from_ast(parse_query("include:tokens c:crane")) == {"tokens"}

    def test_collects_all(self):
        assert includes_from_ast(parse_query("include:all")) == {"all"}

    def test_unknown_category_is_ignored(self):
        assert includes_from_ast(parse_query("include:bogus")) == set()

    def test_absent_is_empty(self):
        assert includes_from_ast(parse_query("c:crane")) == set()

    def test_leaf_negation_stays_on_the_term(self):
        assert parse_query("-c:crane") == leaf("-c:crane")

    def test_redundant_nesting_collapses(self):
        assert parse_query("((c:crane))") == leaf("c:crane")

    def test_empty_query_is_none(self):
        assert parse_query("") is None
        assert parse_query("   ") is None

    def test_stray_dash_is_dropped(self):
        assert parse_query("c:crane -") == leaf("c:crane")
        assert parse_query("-") is None

    def test_empty_or_branch_is_dropped(self):
        assert parse_query("c:crane OR -") == leaf("c:crane")

    def test_unbalanced_open_paren_is_tolerated(self):
        # A mid-typed live-search query still parses; the missing ')' is auto-closed.
        assert parse_query("(c:crane OR c:lion") == BoolGroup(
            "OR", [leaf("c:crane"), leaf("c:lion")]
        )
