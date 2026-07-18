_PAREN_TOKENS = "()"


def tokenize_boolean(query: str) -> list[str]:
    """
    Split a query into tokens for the boolean grammar.

    Behaves like ``tokenize_query`` — whitespace separates tokens and a quoted phrase is one token —
    but additionally emits each parenthesis as its own token, even when flush against a term, so
    ``(c:dragon`` yields ``['(', 'c:dragon']``. Parentheses inside a quoted phrase stay literal, and
    ``OR``/``AND`` are left as ordinary tokens for the parser to classify.

    Parameters
    ----------
    query : str
        Raw search query.

    Returns
    -------
    tokens : list of str
        Query tokens, with ``(`` and ``)`` as standalone entries.
    """
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False

    for char in query:
        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
        elif not in_quotes and char in _PAREN_TOKENS:
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(char)
        elif not in_quotes and char in " \t\n":
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        tokens.append("".join(current))

    return tokens
