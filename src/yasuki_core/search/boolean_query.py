from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from yasuki_core.search.parse_search import INCLUDE_CATEGORIES, SearchTerm, parse_token

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


def active_format_from_ast(node: Node | None) -> str | None:
    """
    Find the single format a query pins for default-print selection, or None.

    Return the value of an exact ``format:``/``arc:`` term reachable through AND groups only — not
    under an ``OR`` (which makes the choice ambiguous) or a ``NOT`` (which negates it) — and only
    when exactly one such term exists.

    Parameters
    ----------
    node : Node or None
        A parsed query AST.

    Returns
    -------
    active_format : str or None
        The pinned format name or block alias, or None when zero or several apply.
    """
    formats = [
        term.value
        for term in _top_level_and_terms(node)
        if term.field == "format" and not term.negated and term.operator in (":", "=")
    ]
    return formats[0] if len(formats) == 1 else None


def includes_from_ast(node: Node | None) -> set[str]:
    """
    Collect the ``include:`` visibility categories a query requests (e.g. ``tokens``, ``all``).

    ``include:`` widens the default-hidden set rather than filtering cards, so it is a query-level
    directive, not a predicate. Gather it from top-level AND terms (an ``include`` under OR or NOT
    is meaningless and ignored).

    Parameters
    ----------
    node : Node or None
        A parsed query AST.

    Returns
    -------
    categories : set of str
        The requested include categories, restricted to the known ones.
    """
    return {
        term.value.lower()
        for term in _top_level_and_terms(node)
        if term.field == "include" and not term.negated and term.value.lower() in INCLUDE_CATEGORIES
    }


def _top_level_and_terms(node: Node | None) -> Iterator[SearchTerm]:
    """Yield the terms reachable through AND groups — not those under an OR or a NOT."""
    if isinstance(node, Term):
        yield node.term
    elif isinstance(node, BoolGroup) and node.op == "AND":
        for child in node.children:
            yield from _top_level_and_terms(child)


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
