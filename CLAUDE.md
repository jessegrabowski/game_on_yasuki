# Game on, Yasuki!

Online client for the Legend of the Five Rings card game: a rules engine, a card database, a deck
builder, a multiplayer web server, and a Tkinter desktop client.

Three packages under `src/`, one-way dependencies (`yasuki_core ← yasuki_web`,
`yasuki_core ← yasuki_gui`; web and gui never import each other):

- **`yasuki_core`** — the rules engine, card models, PostgreSQL access, Scryfall-style card search, the
  card-data + install pipeline, and accounts. Everything else depends on it.
- **`yasuki_web`** — a FastAPI server: card search API, multiplayer rooms and WebSocket play, deck-builder SPA.
- **`yasuki_gui`** — the Tkinter desktop client.

## The shape of it

The **engine** (`yasuki_core.engine`) is a pure, in-memory state machine — it knows nothing of the
database, the web server, or Tk. `TableState`, the `ops` mutators, and `redact` are the shared board
substrate; two surfaces sit on it: the **free-form manual intent layer** (`apply_intent`, driven by the
web server and the GUI sandbox) and the **turn-structured rules layer** (`EngineSession`, driven by the
shipped GUI). The web server and desktop client are two front-ends over the *same* engine, both mutating
through the same `ops` and never shipping unredacted state.

Card data is **file-first**: the committed YAML under `src/yasuki_core/assets/database/` is the source of
truth, loaded into Postgres by the `install/` pipeline (the DB is a derived cache). The accounts database
is separate.

## Subsystem depth: the area skills

Per-subsystem depth (where it lives, what it does, how it fits) is in a skill that fires when you work in
that area — invoke the matching one before a substantial change:

`game-pieces` (card model) · `engine-state` (board state, intents, redaction) · `rules-engine` (turn
play) · `card-data` (YAML + DB schema) · `search` (query language) · `web` (FastAPI server) · `gui`
(Tkinter client) · `accounts` (users/auth).

Full narrative documentation is the Sphinx site under `docs/` — `design/`, `getting_started/`,
`contributing/`.

## Conventions

Global style lives in `~/.claude/CLAUDE.md`; what's specific here, and why:

- **Frozen game pieces** change only through transition methods (which use `object.__setattr__`), so
  every state change is explicit and greppable — don't assign attributes directly.
- **No module-level docstrings.** NumPy-style docstrings on public functions, active voice, current
  contract only (no change-log prose). Comments are rare and explain *why*; names do the documenting.
- **Let pre-commit own formatting** — `ruff` + `ruff format` (line length 100). Don't hand-wrap.
- **Tests** prefer fakes over mocks (never mock your own modules) and shared fixtures; GUI tests mock Tk
  rather than run the main loop.
- **Hot paths** (rendering, card manipulation) stay lean, and exceptions propagate rather than being
  swallowed — a silently-eaten error around a state transition is a recurring bug source.
- Modern Python: PEP 604 unions, PEP 585 generics, no `from __future__ import annotations`.

## Commands

```bash
pixi run play          # Tkinter desktop client
pixi run api           # FastAPI server (port 8000, override with $PORT; api-dev also loads .env)
pixi run test          # Python unit tests (excludes tests/e2e)
pixi run test-js       # JS deck-builder tests
pixi run install-db    # seed the card DB (add --force to reload after YAML edits)
pixi run docs-build    # build the Sphinx docs (docs-api regenerates API pages, docs-serve serves)
pre-commit run --all   # ruff lint + format
```

Run one test through pytest in the env: `pixi run pytest tests/yasuki_core/test_search.py::test_name -p no:playwright`
(or `-k "keyword"`). First-time setup (Postgres, Docker) is in `docs/getting_started/`.
