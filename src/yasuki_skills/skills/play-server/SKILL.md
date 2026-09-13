---
name: play-server
description: >
  Use this for the FastAPI server: the card search API, multiplayer rooms, the WebSocket play
  protocol and its message schemas, the per-seat snapshot broadcast, rate limiting, and the
  deck-builder SPA's backend. Fires on "add an endpoint", "the websocket drops", "add a room",
  "players see each other's hands", "add a message type", "rate limit", and on any change under
  src/yasuki_web/. Read it before touching anything about play. The server is authoritative: it owns
  the shuffle and every seed, drives the engine over the manual intent surface, and redacts state per
  seat, so a message that ships unredacted state hands a player their opponent's hand. Login and saved decks are the accounts skill; the engine internals it drives are
  turns-and-actions.
---

# The play server

## Where it lives

- `src/yasuki_web/main.py`: the app, CORS, static mounts
- `src/yasuki_web/cards.py`: the card search API
- `src/yasuki_web/rooms.py`, `websocket.py`: rooms and the play protocol
- `src/yasuki_web/schemas.py`: the Pydantic wire schemas
- `src/yasuki_web/snapshot.py`, `game_log.py`: what a seat is sent, and the action log
- `src/yasuki_web/rate_limit.py`, `config.py`, `notifications.py`
- `src/yasuki_web/auth.py`, `saved_decks.py`: the accounts surface, covered by that skill
- `src/yasuki_web/static/`: the deck-builder SPA

## What it does

The server is authoritative. Clients send intents, the server applies them to its own copy of the
board through the engine's manual intent surface, and broadcasts a redacted snapshot per seat. Each
player receives a view with the other's hidden zones already removed, so no client is trusted to
censor a shared state. Randomness lives here for the same reason: a seed taken from a client lets a
player pick their own shuffle.

Every message crossing the wire has a Pydantic schema. Adding a message type means adding its schema
and teaching both ends. Nothing negotiates a protocol version, so a client and server that disagree
fail at parse time; the `bump_version` counter on room state is a snapshot sequence number rather
than a protocol version, and does not help here.

## What checks it

- The suite, including the websocket protocol tests
- `pixi run test-js`: the deck-builder JavaScript tests
- `pixi run test-e2e`: the Playwright end-to-end suite, which is excluded from `pixi run test`

## How it fits

`docs/design/web-app.md` is the reference: the endpoints, the room lifecycle, the protocol and the
snapshot contract. `docs/design/package_boundaries.md` states the rule this package most often tests
-- the web server may import `yasuki_core` and must never import `yasuki_gui`.

The engine surface it drives is the `turns-and-actions` skill, the query language behind the search
API is `card-search`, and login, sessions and saved decks are `accounts`.
