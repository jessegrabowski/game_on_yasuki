# Game on, Yasuki!

Instructions for coding agents working in this repository. Read this before changing anything. It is
harness-neutral: everything here applies whatever tool you are running under.

Online client for the Legend of the Five Rings card game: a rules engine, a card database, a deck
builder, a multiplayer web server, and a Tkinter desktop client.

## The three packages

Under `src/`, with one-way dependencies (`yasuki_core <- yasuki_web`, `yasuki_core <- yasuki_gui`;
web and gui never import each other):

| Package | Role |
|---|---|
| `yasuki_core` | Rules engine, card models, PostgreSQL access, card search, the card-data and install pipeline, accounts |
| `yasuki_web` | FastAPI server: card search API, multiplayer rooms and WebSocket play, deck-builder SPA |
| `yasuki_gui` | Tkinter desktop client |

The engine (`yasuki_core.engine`) is a pure, in-memory state machine that knows nothing of the
database, the web server, or Tk. `TableState`, the `ops` mutators and `redact` are the shared board
substrate. Two surfaces sit on it: the free-form manual intent layer (`apply_intent`, driven by the
web server and the GUI sandbox) and the turn-structured rules layer (`EngineSession`, driven by the
shipped GUI). Both front-ends mutate through the same `ops`, and neither ever ships unredacted state.

`docs/design/package_boundaries.md` states the boundaries. Nothing enforces them, so they are yours
to hold.

## Compose, then add

The engine grows by composing the terms it already has: effects, decisions, events, moments, board
queries and registries. Before adding any of those, decompose the card or rule text into its
rule-level verbs and find the existing term for each. Add a term only when the CR names a primitive
nothing composes to. Name it for the rule's verb, never for a card, keyword or mechanic. In the same
change, migrate every bespoke path it replaces and delete them. Review here sends back a new term
with one caller, or a second way of saying something the vocabulary already says.
`docs/design/build_from_the_vocabulary.md` is the procedure, with worked examples. Read it before
adding to the engine.

## The skills

This project ships agent skills, one per kind of task, which `yasuki-install-skills` places where
your agent reads them (see `docs/contributing/agent_skills.md`). Each one names the source paths it
covers in its own description, so the skill that fits what you are doing should already be in
context.

After moving or renaming a module, grep `src/yasuki_skills/skills/` for the old path: the pre-commit
check catches a name that no longer resolves, but not prose that has quietly stopped being true.

## Commands

```bash
pixi run play          # Tkinter desktop client
pixi run api           # FastAPI server (port 8000, override with $PORT; api-dev also loads .env)
pixi run test          # Python unit tests (excludes tests/e2e and the skills package)
pixi run test-skills   # the agent-skills package and its hooks
pixi run test-js       # JS deck-builder tests
pixi run install-db    # seed the card DB (add --force to reload after YAML edits)
pixi run docs-build    # build the Sphinx docs (docs-api regenerates API pages, docs-serve serves)
pre-commit run --all   # ruff lint + format, plus the card and docs hooks
```

One test: `pixi run pytest tests/yasuki_core/test_search.py::test_name -p no:playwright`, or
`-k "keyword"`. First-time setup, including Postgres and Docker, is in `docs/getting_started/`.

## Code conventions

Cards and other game objects are frozen dataclasses that change only through their transition
methods, which use `object.__setattr__`. Never assign to their attributes directly, so that every
state change stays explicit and greppable.

Modules carry no docstrings. Public functions get NumPy-style docstrings in active voice, stating
the current contract and no change-log prose. A docstring that explains what the code does, instead
of adding information, is a sign the code wants a better name.

Comments are rare and explain why. Names do the documenting, and a comment is never a section
heading or a changelog entry. The one exception is `engine/rules/cards/`, where a header per card is
required and checked by a hook.

Let pre-commit own formatting: `ruff` and `ruff format` at line length 100. Do not hand-wrap code to
some other width.

Rendering and card manipulation are hot paths. They carry no redundant checks and no work that could
be hoisted out of a loop, and exceptions propagate rather than being swallowed. A silently eaten
error around a state transition is a recurring source of bugs here.

Write modern Python: PEP 604 unions, PEP 585 generics, and no `from __future__ import annotations`.

Code, comments, docstrings and documentation are ASCII. Write `->`, `<-`, `--` and `>=`, and spell
out Greek names. Non-ASCII belongs only where the content cannot exist without it, such as a card
title that is actually spelled that way. Use American English everywhere.

## Card data is file-first

The committed YAML under `src/yasuki_core/assets/database/` is the source of truth. The `install/`
pipeline loads it into PostgreSQL, and that database is a derived cache: safe to drop and rebuild,
and never the place to fix a card. `pixi run install-db` does nothing where a row already exists, so
after editing YAML you need `--force` to see the change.

The accounts database is a separate PostgreSQL instance, isolated so that reseeding cards can never
reach user data.

## Implementing a card

Start at `docs/contributing/adding_a_card.md`, which maps printed wording to the hook that models it.
Three things there are easy to get wrong. A card's id is derived from its printed title, so a handler
keyed on a typo registers happily and never fires. A card is implemented once, in the module for the
set that printed it first. And a handler returns effects instead of mutating the board.

The `registration-audit`, `card-layout` and `card-index` pre-commit hooks check all of this. Run
`pre-commit run --all` before you decide you are finished.

## Tests

Every new source file gets a test file mirroring its path under `tests/`. Prefer fakes over mocks,
and never mock this project's own modules; shared fixtures beat bespoke setup, and GUI tests mock Tk
instead of running the main loop. Coverage should be useful: few conditions, real scenarios. A
behavior change and the test that covers it belong in the same commit.

## Documentation

The Sphinx site under `docs/` is the narrative reference, and the place to look before reverse
engineering the code:

- `docs/getting_started/`: installing, the database, running each front-end.
- `docs/design/`: how the software is put together, including `package_boundaries.md`,
  `database.md`, `search.md`, `web-app.md` and `tk-client.md`.
- `docs/design/systems/`: one page per engine system, covering turn flow, triggers, effects, gold,
  stats, battle, decisions, the replay log and the rest.
- `docs/contributing/`: modeling cards, written for someone who knows L5R but not this codebase.

The docs build is strict: `-W` plus `nitpicky`, so a cross-reference naming a symbol that moved fails
the build instead of rendering as plain text. Code samples in the pages are pulled from the source
with `literalinclude`, so a rename that breaks a sample also fails the build. Do not paste code into
a page when an include can point at it.
