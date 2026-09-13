---
name: search
description: >
  Use this whenever you work on the card search query language in src/yasuki_core/search — adding or
  changing search fields/operators/keywords, the tokenizer or parser, boolean combination of terms, or
  how a query becomes filter options / SQL against the card database — and read it before adding an
  operator, since it usually means touching both the parser here and the column mapping it compiles to.
  Covers the Scryfall-style query DSL used by the card API and the deck builder. The database schema the
  query runs against is the card-data skill.
---

# Card search query language

## Where it lives

`src/yasuki_core/search/`:

- `parse_search.py` — the field/operator query language
- `boolean_query.py` — the boolean AST (AND/OR/NOT combination)
- `__init__.py` — the curated public surface (`__all__`)

## What it does

A Scryfall-style query language for the card database. `parse_search.py` exposes `SearchTerm`,
`ParsedQuery`, the field vocabulary (`FIELD_ALIASES`, `NUMERIC_FIELDS`, `normalize_field_name`), the
tokenizer/parser (`tokenize_query`, `parse_token`, `parse_search_query`), and the query-to-filter
compilation (`build_filter_options`, `parse_and_build_query`). It handles field filters
(`c:crane t:personality`), numeric operators (`force>=4`), `is:` keywords, and negation. `boolean_query.py`
builds an AST of `Node`/`Not`/`Term` via `parse_query`, plus helpers like `active_format_from_ast` and
`includes_from_ast`. Together they turn a query string into filter options / SQL that run against the
card tables.

## How it fits the big picture

Search is consumed by the web card API (`yasuki_web/cards.py`, see the `web` skill) and the deck-builder
SPA; it queries the card schema (see the `card-data` skill). Adding an operator usually means touching
both the parser here and the field/column mapping it compiles to.

Full narrative: `docs/design/search.md` (the query language as documented for users).
