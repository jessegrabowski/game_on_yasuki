---
name: card-search
description: >
  Use this for the Scryfall-style query language the card API and the deck builder run on: adding or
  changing a search field, operator or keyword, the tokenizer and parser, how terms combine with and
  / or / not, and how a parsed query becomes SQL against the card database. Fires on "add a search
  field", "why does this query return nothing", "search for cards with", "the parser chokes on",
  "add an operator", and on any change under src/yasuki_core/search/. Read it before adding an
  operator, because a field usually has to be taught in two places, the parser that accepts it and
  the compiler that maps it onto a column. A field accepted but not compiled fails silently with an
  empty result. The schema the query runs against is the card-data skill; the HTTP endpoint
  that serves it is play-server.
---

# The card search language

## Where it lives

- `src/yasuki_core/search/parse_search.py`: the tokenizer and parser: fields, operators, values
- `src/yasuki_core/search/boolean_query.py`: combining terms with and / or / not
- `src/yasuki_core/search/compile_sql.py`: the parsed query as SQL against the card tables
- `src/yasuki_web/cards.py`: the HTTP surface that calls it

## What it does

A query string becomes a parse tree, and the tree becomes SQL. The two halves are separate on
purpose: the parser knows the language, the compiler knows the schema, and neither needs the other's
vocabulary. That split is also the trap. Adding a field to the parser without mapping it in the
compiler yields a query that parses, runs, and returns nothing, with no error anywhere.

Field names are part of the public surface: the deck builder's search box and anyone's bookmarked
query use them, so renaming one breaks saved queries.

## What checks it

- The suite, which parses and compiles a corpus of queries and asserts the rows that come back
- `docs-api` (pre-commit): a renamed public symbol fails the documentation build

## How it fits

`docs/design/search.md` is the reference: the grammar, every field and operator, and how a term
becomes a filter. The columns those fields map onto are the `card-data` skill, and the API endpoint
and its rate limiting are `play-server`.
