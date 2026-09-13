---
name: gui
description: >
  Use this whenever you work on the Tkinter desktop client in src/yasuki_gui — board rendering, sprites
  and visuals, drag-and-drop, hit-testing, the field view, the controller, hotkeys, or the in-client
  deck builder — and read it before changing rendering or input, since the client runs two engine modes
  (shipped rules vs local sandbox) that behave differently. Covers how the desktop client builds state
  from a deck, drives the engine, and renders redacted state. The engine surfaces it calls are the
  rules-engine (shipped mode) and engine-state (sandbox mode) skills.
---

# Desktop client (Tkinter)

## Where it lives

`src/yasuki_gui/`:

- `__main__.py` — entry point; `session.py` — build state from a deck
- `services/game_runner.py` — `GameRunner`; `services/game_host.py` — the desktop controller
- `field_view.py` — board rendering; `controller.py` + `services/` (`drag`, `hittest`, `actions`,
  `permissions`) — input
- `visuals/` — sprites, zones, hand; `ui/` — dialogs, menus, `deck_builder/`; `theme`, `layout`, `config`

## What it does

`session.build_state_from_deck` turns a deck into a `TableState` (the same
`parse_deck_yaml → resolve_decklist → setup_seat` pipeline the web server uses). The **shipped app**
drives the rules `EngineSession` through a `GameRunner` (`services/game_runner.py`): `view()` → `project`,
`legal_actions`, `act`/`submit`, and it auto-runs the opponent. `FieldView.render_snapshot` draws
`GameView.table` — a redacted `ViewSnapshot`.

A **manual sandbox path** also exists: `FieldView.dispatch` calls `apply_intent` directly on the local
`TableState`, and `FieldController` + `services/actions.py` turn drag/click into `Intent`s (`MoveCard`,
`Bow`, `SpawnCard`…). `rules_mode` is on whenever a rules snapshot is set, which disables the sandbox
dispatch. `ui/deck_builder/` is the in-client deck editor.

## How it fits the big picture

The desktop client is the second front-end over the engine — local and single-process. In its shipped
mode it uses the **rules surface** (see the `rules-engine` skill); in sandbox mode it uses the **manual
intent surface** (see the `engine-state` skill). It shares the setup pipeline and the `redact` snapshot
contract with the web server (see the `web` skill). An optional config file (hotkeys, DSN), copied from `config.yaml.example`, is documented
in `docs/getting_started/running.md`.

Full narrative: `docs/design/tk-client.md`.
