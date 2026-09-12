# Core engine design

The rules engine lives in `yasuki_core.engine`. It is a pure, in-memory state machine: it holds the
table state, accepts intents (requested actions), validates and applies them through the rules layer,
and emits an intent log plus redacted per-player views. It has no knowledge of the database, the web
server, or the desktop client. Those consume it.

```{note}
This page is an outline. The full write-up is still being written; the bullets below are the intended
sections.
```

The pieces, at a glance:

- **Table state** (`engine/table.py`, `engine/players.py`, `engine/zones.py`) is the authoritative game
  state: players, their zones (hand, provinces, dynasty/fate decks, discards), and the cards in them.
- **Sessions & intents** (`engine/session.py`, `engine/intents.py`, `engine/intent_handlers.py`,
  `engine/ops.py`) hold the intent vocabulary, the interpreter that applies it, and how an action is
  requested, validated, and applied as a state transition.
- **The rules layer** (`engine/rules/`) holds state, flow (turn/phase progression), actions,
  decisions, abilities, effects, and triggers.
- **Redaction** (`engine/redaction.py`) produces the per-player views clients are allowed to see.
- **Replay** (`engine/replay/`) holds the wire codec, the initial position a tape replays from, and the
  two tapes themselves: `intent_log.py` for the manual surface and `game_log.py` for the rules one.

To be documented here:

- The state model and zone invariants.
- The intent -> validation -> apply -> log lifecycle.
- How abilities and effects are registered and resolved.
- The redaction boundary (what each seat may observe).
