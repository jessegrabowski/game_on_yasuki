from dataclasses import dataclass
from typing import Literal

from yasuki_core.search.parse_search import SearchTerm, parse_token

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


# AST for the boolean grammar. `Term` is a leaf (one field:op:value, carrying its own leaf
# negation); `Not` negates a subtree (from `-(...)`); `BoolGroup` combines children under AND or OR.
class Node:
    pass


@dataclass(frozen=True)
class Term(Node):
    term: SearchTerm


@dataclass(frozen=True)
class Not(Node):
    child: Node


@dataclass(frozen=True)
class BoolGroup(Node):
    op: Literal["AND", "OR"]
    children: list[Node]


def parse_query(query: str) -> Node | None:
    """
    Parse a search query into a boolean AST.

    Grammar (precedence ``NOT > AND > OR``, parentheses overriding): terms juxtaposed with
    whitespace are ANDed, ``OR`` combines alternatives, ``-`` negates the leaf or ``(group)`` it
    prefixes. Unbalanced parentheses are tolerated (auto-closed) and stray ``-`` tokens are dropped,
    so a mid-typed live-search query still parses.

    Parameters
    ----------
    query : str
        Raw search query.

    Returns
    -------
    root : Node or None
        The AST root, or None for a query with no constraints (empty, or only stray dashes).
    """
    return _Parser(tokenize_boolean(query)).parse()


def _group(op: Literal["AND", "OR"], children: list[Node | None]) -> Node | None:
    """Build a group, dropping empty children and collapsing a lone child to itself."""
    present = [child for child in children if child is not None]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    return BoolGroup(op, present)


class _Parser:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Node | None:
        return self._parse_or()

    def _peek(self, offset: int = 0) -> str | None:
        index = self.pos + offset
        return self.tokens[index] if index < len(self.tokens) else None

    def _advance(self) -> str:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    @staticmethod
    def _is_keyword(token: str | None, word: str) -> bool:
        return token is not None and token.upper() == word

    def _parse_or(self) -> Node | None:
        children = [self._parse_and()]
        while self._is_keyword(self._peek(), "OR"):
            self._advance()
            children.append(self._parse_and())
        return _group("OR", children)

    def _parse_and(self) -> Node | None:
        children: list[Node | None] = []
        while True:
            token = self._peek()
            if token is None or token == ")" or self._is_keyword(token, "OR"):
                break
            if self._is_keyword(token, "AND"):
                self._advance()  # explicit AND, same as juxtaposition
                continue
            if token == "-" and self._peek(1) != "(":
                self._advance()  # stray dash (leaf negation is glued into its term token)
                continue
            children.append(self._parse_unary())
        return _group("AND", children)

    def _parse_unary(self) -> Node | None:
        if self._peek() == "-":  # only a group-negating '-(' reaches here
            self._advance()
            atom = self._parse_atom()
            return Not(atom) if atom is not None else None
        return self._parse_atom()

    def _parse_atom(self) -> Node | None:
        token = self._peek()
        if token is None:
            return None
        if token == "(":
            self._advance()
            inner = self._parse_or()
            if self._peek() == ")":
                self._advance()  # tolerate a missing close paren
            return inner
        self._advance()
        return Term(parse_token(token))
