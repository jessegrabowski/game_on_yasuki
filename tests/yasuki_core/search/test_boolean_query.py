from yasuki_core.search.boolean_query import tokenize_boolean


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
