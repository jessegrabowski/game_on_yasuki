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
shipped GUI). Both front-ends mutate through the same `ops` and neither ever ships unredacted state.

`docs/design/package_boundaries.md` states the boundaries. Nothing enforces them, so they are yours
to hold.

## Commands

```bash
pixi run play          # Tkinter desktop client
pixi run api           # FastAPI server (port 8000, override with $PORT; api-dev also loads .env)
pixi run test          # Python unit tests (excludes tests/e2e)
pixi run test-js       # JS deck-builder tests
pixi run install-db    # seed the card DB (add --force to reload after YAML edits)
pixi run docs-build    # build the Sphinx docs (docs-api regenerates API pages, docs-serve serves)
pre-commit run --all   # ruff lint + format, plus the card and docs hooks
```

One test: `pixi run pytest tests/yasuki_core/test_search.py::test_name -p no:playwright`, or
`-k "keyword"`. First-time setup, including Postgres and Docker, is in `docs/getting_started/`.

## Code conventions

- **Frozen game pieces.** Cards and other game objects are frozen dataclasses that change only
  through their transition methods, which use `object.__setattr__`. Never assign to their attributes
  directly: every state change should be explicit and greppable.
- **No module-level docstrings.** Public functions get NumPy-style docstrings, active voice, stating
  the current contract and no change-log prose. A docstring that explains what the code does rather
  than adding information is a sign the code wants a better name.
- **Comments are rare and explain why.** Names do the documenting. Never use a comment as a section
  heading or a changelog entry. The one exception is `engine/rules/cards/`, where a header per card
  is required and checked by a hook.
- **Let pre-commit own formatting.** `ruff` and `ruff format` at line length 100. Do not hand-wrap
  code to some other width.
- **Hot paths stay lean.** Rendering and card manipulation carry no redundant checks and no work that
  could be hoisted out of a loop. Let exceptions propagate rather than swallowing them; a silently
  eaten error around a state transition is a recurring source of bugs here.
- **Modern Python.** PEP 604 unions, PEP 585 generics, no `from __future__ import annotations`.
- **ASCII only** in code, comments, docstrings and documentation. Write `->`, `<-`, `--`, `>=` and
  spelled-out Greek names rather than the Unicode glyphs. Non-ASCII is allowed only where the content
  cannot exist without it, such as a card title that is actually spelled that way.
- **American English** in every written artifact.

## Card data is file-first

The committed YAML under `src/yasuki_core/assets/database/` is the source of truth. The `install/`
pipeline loads it into PostgreSQL, and that database is a derived cache: it is safe to drop and
rebuild, and it is never the place to fix a card. `pixi run install-db` does nothing where a row
already exists, so after editing YAML you need `--force` to see the change.

The accounts database is a separate PostgreSQL instance, deliberately isolated so that reseeding
cards can never reach user data.

## Implementing a card

Start at `docs/contributing/adding_a_card.md`, which maps printed wording to the hook that models it.
Three things there are easy to get wrong and worth knowing before you write a handler: a card's id is
derived from its printed title rather than written down, so a handler keyed on a typo registers
happily and never fires; a card is implemented once, in the module for the set that printed it first;
and a handler returns effects rather than mutating the board.

The `registration-audit`, `card-layout` and `card-index` pre-commit hooks check all of this. Run
`pre-commit run --all` before you decide you are finished.

## Tests

- Every new source file gets a test file mirroring its path under `tests/`.
- Prefer fakes over mocks, and never mock this project's own modules. Shared fixtures over bespoke
  setup. GUI tests mock Tk rather than running the main loop.
- Coverage should be useful rather than exhaustive: few conditions, real scenarios.
- A behavior change and the test that covers it belong in the same commit.

## Documentation

The Sphinx site under `docs/` is the narrative reference and the place to look before reverse
engineering the code:

- `docs/getting_started/` -- installing, the database, running each front-end.
- `docs/design/` -- how the software is put together, including `package_boundaries.md`,
  `database.md`, `search.md`, `web-app.md` and `tk-client.md`.
- `docs/design/systems/` -- one page per engine system: turn flow, triggers, effects, gold, stats,
  battle, decisions, the replay log and the rest.
- `docs/contributing/` -- modeling cards, written for someone who knows L5R rather than this codebase.

The docs build is strict: `-W` plus `nitpicky`, so a cross-reference naming a symbol that moved fails
the build rather than rendering as plain text. Code samples in the pages are pulled from the source
with `literalinclude`, so a rename that breaks a sample also fails the build. Do not paste code into
a page when an include can point at it.
