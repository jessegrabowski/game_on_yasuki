---
name: engine-state
description: >
  Use this whenever you touch the game board's low-level state, mutation, or view layers in
  src/yasuki_core/engine — board or table state, zones and their invariants, the ops mutators, the
  Intent dataclasses or apply_intent, redaction, snapshots, or serialization — and read it before the
  change rather than inferring the structure from the code, even for a one-line fix. Covers TableState
  (the shared, authoritative board substrate), the ops mutators every board change funnels through, the
  free-form "manual" intent surface the web server and desktop sandbox drive, and the per-seat redaction
  and wire serialization. The turn-structured rules layer (EngineSession, rules/) is a separate surface
  on the same substrate — see the rules-engine skill.
---

# Engine board state, mutation, and the intent surface

## Where it lives

`src/yasuki_core/engine/`:

- `table.py` — `TableState` (and `SeatInfo`; the `ZoneKey` / `DeckKey` / `BoardPos` addressing keys)
- `zones.py` — `Zone` and its subclasses
- `ops.py` — the low-level board mutators
- `intents.py` — the `Intent` dataclasses and `apply_intent`
- `redaction.py`, `snapshot.py`, `serialization.py` — per-seat views, the replay seed, and the wire codec

## What it does

**Board substrate.** `TableState` is the authoritative per-game board: `seats` (`SeatInfo`), role-keyed
`zones` and `decks` per seat, a shared `battlefield`, plus the side tables that frozen cards can't carry
themselves — `positions`, `attachments` (child→parent graph), `cards_by_id` — and a monotonic `seq`
bumped on every change. `Zone`s enforce entry invariants (wrong side or over capacity is rejected;
`ProvinceZone` holds one, `HandZone` is Fate-only).

**Mutation primitive.** `ops.py` (`move_card`, `attach`, `fill_province`, `draw_to_hand`, `set_honor`,
`straighten`…) is where every board change funnels through, and where zone-entry and attachment rules
are actually enforced. Both surfaces below mutate through `ops` — it is shared, not manual-only.

**The manual / free-form surface.** An `Intent` (`intents.py`) is a frozen dataclass for one board
manipulation (`MoveCard`, `Bow`, `SpawnCard`, `Attach`…). `apply_intent(state, seat, intent) -> [Event]`
validates ownership/side/capacity and dispatches to the `ops` mutators; `seq` advances only if the board
changed. This is a free-form board with no turn structure.

**Views and wire.** `redact(state, viewer)` produces a per-seat `ViewSnapshot`, replacing cards the
viewer may not identify with `HiddenCard` stubs — *the* disclosure boundary, so never send unredacted
state to a client. `snapshot.InitialRecord` is the full-state seed a log replays from; `serialization.py`
is the wire codec for cards, keys, and intents.

## How it fits the big picture

Two surfaces sit on this same substrate, and **both mutate through `ops`**:

- The **manual intent surface** (`apply_intent`) — a free-form board with no turn rules. Driven by the
  web server (server-authoritative, networked; see the `web` skill) and by the desktop client's local
  sandbox mode (see the `gui` skill).
- The **rules engine** (`EngineSession`, `rules/`; see the `rules-engine` skill) — turn-structured play.
  It wraps this `TableState` in a `GameState` and calls the same `ops` **directly** — it never goes
  through `apply_intent` (effects apply via `apply_effect`).

So `intents`/`apply_intent` is one surface (the manual/free-form one), *not* the universal action model;
the `TableState`, `ops`, and `redact` beneath it are the implementation-agnostic core that every layer
shares. The cards held here are frozen `L5RCard`s (see the `game-pieces` skill) — mutate them only
through their transition methods.

Full narrative: `docs/design/engine.md`.
