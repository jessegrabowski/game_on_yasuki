---
name: rules-engine
description: >
  Use this whenever you work on the turn-structured rules layer in src/yasuki_core/engine — the
  EngineSession API (project/legal_actions/act/submit/cancel/undo), GameState (turn/phase/gold/
  decisions), the high-level Actions (Recruit, Pass, DynastyDiscard, Legacy, ActivateAbility), or
  anything under engine/rules/ (state, effects, legality, triggers, projection, and the turn,
  abilities, gold, stats, rulebook, battle, board, units and vocabulary packages) — and read it
  before changing turn, phase, ability, or effect logic rather than
  reverse-engineering the flow from the code. Covers the rules-driven game surface. The free-form manual
  surface (Intent/apply_intent) and the shared board substrate it sits on are the engine-state skill.
---

# Rules engine (turn-structured play)

## Where it lives

`src/yasuki_core/engine/`:

- `session.py` — `EngineSession` (the client surface for a rules game)
- `replay/` — `game_log.py`, `intent_log.py`, `snapshot.py`, `serialization.py`
- `rules/` holds eight modules at the top and nine subject packages beneath them. The eight:
  `state.py`, `effects.py`, `legality.py`, `triggers.py`, `projection.py`, `attack_effects.py`,
  `state_based_actions.py`
- `rules/vocabulary/` — the leaf layer nothing else in `rules/` may be imported by: `actions.py`,
  `decisions.py`, `game_events.py`, `keywords.py`, `modifiers.py`, `segments.py`, `victory.py`,
  `work.py`
- `rules/abilities/`, `battle/`, `board/`, `gold/`, `rulebook/`, `stats/`, `turn/`, `units/` — one
  package per subject
- `rules/cards/` — one module per card set, mirroring the set YAML; a card is implemented once, in
  the set that printed it first (see the `card-authoring` skill)

## What it does

`EngineSession` is the single client-facing surface for a rules-driven game. It owns a `GameState` plus a
replayable `GameLog`; `start` snapshots a dealt `TableState` into the log so the log replays exactly.
Channels: `project(seat)` → a per-seat `GameView`, `legal_actions(seat)`, and `act` / `submit` /
`cancel` / `undo_last`. Actions are high-level rules moves (`Pass`, `Recruit`, `DynastyDiscard`,
`Legacy`, `ActivateAbility`).

`GameState` (`rules/state.py`) wraps `TableState` with turn bookkeeping — `first_player`, `active`,
`turn`, `phase`, per-seat `gold`, `favor_holder`, `once_per` flags, a `pending: DecisionRequest | None`,
and a `stack` of deferred `WorkItem`s. `turn/` is the turn and phase machine and
`vocabulary/work.py` carries the deferred multi-step sequences (finishing a Recruit after payment).
`abilities/` handles activatability and cost payment, `gold/` prices and pays, and `stats/` is the
effective-stat read path. `effects.py` is the effect vocabulary a card returns and `legality.py`
decides which actions a seat may take. `triggers.py` runs the effect-and-trigger cascade to a
fixpoint and is the single mutation boundary through `apply_effect`. `vocabulary/decisions.py`
pauses for player choices, answered by an `Agent` from `yasuki_core.bots` — human UI, AI, network,
or a test double. `projection.py` builds the redacted `GameView`, and `replay/game_log.py` is the
`Act`/`Answer`/`Cancel` tape with replay.

Crucially, the rules layer mutates the board through the **same `ops` mutators** the manual surface uses
(and `apply_effect` for effects) — it never goes through `apply_intent`.

## How it fits the big picture

This is one of two surfaces over the shared board substrate (`TableState`, `ops`, redaction — see the
`engine-state` skill); the other is the free-form manual intent surface. The **shipped desktop client**
drives this rules surface through a `GameRunner` (see the `gui` skill); the web server currently drives
the manual surface instead (see the `web` skill). Effects and abilities key off a card's `printed_id`
(see the `game-pieces` skill).

Full narrative: `docs/design/engine.md` is still a stub. The subsystems documented so far are
`docs/design/systems/triggers-and-the-cascade.md` (the effect-and-trigger worklist),
`docs/design/systems/stats.md` (the `effective_*` read path and the five ongoing effects) and
`docs/design/systems/gold.md` (production, the bow-time window, affordability and payment). The
boundaries this layer holds to are in `docs/design/package_boundaries.md`.
