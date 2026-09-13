---
name: web
description: >
  Use this whenever you work on the FastAPI server in src/yasuki_web — REST endpoints, the card search
  API, multiplayer rooms and the WebSocket play protocol, the per-seat snapshot broadcast, the Pydantic
  wire schemas, rate limiting, or the deck-builder SPA backend — and read it before changing anything
  about play or the protocol, since the server is authoritative and drives the engine in a specific way.
  Covers how the web server drives the engine (server-authoritative, over the manual intent surface).
  Login/accounts is the accounts skill; the engine internals it calls are the engine-state skill.
---

# Web server (FastAPI)

## Where it lives

`src/yasuki_web/`:

- `main.py` — the FastAPI `app`, middleware, routers, static mounts
- `cards.py` — the card search API; `config.py`, `rate_limit.py`, `notifications.py`
- `rooms.py`, `websocket.py`, `snapshot.py`, `game_log.py` — multiplayer play
- `schemas.py` — Pydantic wire messages; `auth.py`, `saved_decks.py` — accounts surface
- `static/` — the deck-builder and site SPAs

## What it does

`main.py` constructs the `app` at import (idiomatic FastAPI; the DB pool and the accounts-schema
migration run in the `lifespan` startup, not at import). `cards.py` serves the search API (see the
`search` skill).

Multiplayer is **server-authoritative over the manual intent surface**. A `GameRoom` (`websocket.py`)
owns the truth — a `TableState` plus an append-only `ActionLog` per room. A wire `IntentEnvelope`
(`schemas.py`) is decoded to a core `Intent`, applied via `apply_and_log`, and the server broadcasts a
**per-seat** `ServerSnapshot` built from `serialize_snapshot(redact(state, seat))`, so bytes a seat
shouldn't see never leave the server. DB-backed ops (spawn ids, deck search) are pre-resolved
server-side to keep the pure intent layer replay-safe. `schemas.py` holds the Pydantic message models;
`game_log.py` builds redaction-safe shared log lines.

## How it fits the big picture

The web server is one of two front-ends over the engine. It drives the **manual intent surface** — not
the rules `EngineSession` (see the `engine-state` and `rules-engine` skills for that distinction). The
setup pipeline (`parse_deck_yaml → resolve_decklist → setup_seat`) and the `redact` disclosure boundary
are shared with the desktop client (see the `gui` skill). Login, sessions, and saved decks go through the
`accounts` skill; card data through `card-data`.

Full narrative: `docs/design/web-app.md` (the REST + WebSocket protocol).
