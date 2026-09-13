---
name: turns-and-actions
description: >
  Use this for how a game proceeds rather than what a card says: the turn and its phases, which
  actions a seat may take and why one is illegal, how an action that pauses for an answer resumes,
  what a handler is handed in GameState, how to ask the board a question, and the replay log both
  surfaces write to. Fires on "add a phase", "why is this action illegal", "the turn does not
  advance", "add an action", "how do I get the cards in a province", "what is in GameState",
  "resume after a decision", and on engine work under rules/turn, rules/board, rules/legality,
  rules/state or engine/replay. Read it before changing flow: the two surfaces over this
  board, the rules layer and the free-form intent layer, allow different things, and both have to
  keep the log honest. What a card may say is the card-vocabulary skill;
  writing a printed card's handler is implementing-a-card.
---

# Turns, actions and the board

## Where it lives

- `src/yasuki_core/engine/table.py`, `zones.py`, `players.py`: the shared board substrate
- `src/yasuki_core/engine/ops.py`: every board mutation funnels through these
- `src/yasuki_core/engine/intents.py`, `intent_handlers.py`: the free-form manual surface
- `src/yasuki_core/engine/redaction.py`: per-seat views; no surface ships unredacted state
- `src/yasuki_core/engine/session.py`, `driver.py`: the turn-structured surface
- `src/yasuki_core/engine/rules/state.py`: `GameState`, which is all a card function is handed
- `src/yasuki_core/engine/rules/turn/`: `structure.py`, `sequence.py`, `action_sequence.py`,
  `provinces.py`
- `src/yasuki_core/engine/rules/legality.py`, `projection.py`, `state_based_actions.py`
- `src/yasuki_core/engine/rules/board/queries.py`: the vocabulary for asking the board a question
- `src/yasuki_core/engine/replay/`: `game_log.py`, `intent_log.py`, `snapshot.py`,
  `serialization.py`

## What it does

Two surfaces sit on one board. The rules layer runs a turn: phases in order, actions offered only
when legal, decisions that pause the game and resume where they left off. The manual intent layer
imposes no legality at all, which is what the web sandbox and the desktop sandbox drive. Both mutate
through the same `ops` and both write the same log.

A handler is handed a `GameState` and nothing else. Reaching into `game.table` and filtering by hand
is nearly always rewriting a function in `rules/board/queries.py`, which is the layer that exists so
that card code does not have to know the board's shape.

## What checks it

- The suite, including the tests that replay a logged game and assert the same end state
- `docs-api` (pre-commit): a renamed public symbol fails the documentation build

## How it fits

`docs/design/engine.md` is the overview of the two surfaces. Then, under `docs/design/systems/`:
`turn-flow.md`, `actions-and-legality.md`, `action-lifecycles.md`, `game-state.md`,
`board-queries.md` and `the-replay-log.md`. `docs/design/package_boundaries.md` states the one-way
dependency rule that engine work is most likely to break.

What a card may say into this machinery is the `card-vocabulary` skill. The web server and the
desktop client are two front-ends over it, covered by `play-server` and `desktop-client`.
