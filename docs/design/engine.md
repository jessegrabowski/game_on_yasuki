# Core Engine Design

The rules engine lives in `yasuki_core.engine`. It is a pure, in-memory state machine: it holds the
table state, accepts intents (requested actions), validates and applies them through the rules layer,
and emits an action log plus redacted per-player views. It has no knowledge of the database, the web
server, or the desktop client — those consume it.

```{note}
This page is an outline. The full write-up is still being written; the bullets below are the intended
sections.
```

The pieces, at a glance:

- **Table state** (`engine/table.py`, `engine/players.py`, `engine/zones.py`) — the authoritative game
  state: players, their zones (hand, provinces, dynasty/fate decks, discards), and the cards in them.
- **Sessions & intents** (`engine/session.py`, `engine/intents.py`, `engine/ops.py`) — how an action is
  requested, validated, and applied as a state transition.
- **The rules layer** (`engine/rules/`) — state, flow (turn/phase progression), actions, decisions,
  abilities, effects, and triggers.
- **Redaction & snapshots** (`engine/redaction.py`, `engine/snapshot.py`, `engine/serialization.py`) —
  producing the per-player views that clients are allowed to see.

To be documented here:

- The state model and zone invariants.
- The intent → validation → apply → log lifecycle.
- How abilities and effects are registered and resolved.
- The redaction boundary (what each seat may observe).
