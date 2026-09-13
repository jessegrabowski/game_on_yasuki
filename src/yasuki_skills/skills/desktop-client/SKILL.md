---
name: desktop-client
description: >
  Use this for the Tkinter desktop client: drawing the board, sprites and zones, drag and drop,
  hit-testing, the controller and its hotkeys, the in-client deck builder, and how the client drives
  the engine. Fires on "the board looks wrong", "cards overlap", "drag and drop", "add a hotkey",
  "the client freezes", "open the deck builder", "run the game locally", and on any change under
  src/yasuki_gui/. Read it before changing rendering or input, because the client runs the engine in
  two different modes, the shipped rules session and a no-legality sandbox, and code that assumes
  one behaves surprisingly in the other. The engine surfaces it calls are the
  turns-and-actions skill.
---

# The desktop client

## Where it lives

- `src/yasuki_gui/__main__.py`: the entry point, behind `pixi run play`
- `src/yasuki_gui/field_view.py`: board rendering
- `src/yasuki_gui/controller.py`: user interaction
- `src/yasuki_gui/services/`: `game_host.py`, `game_runner.py`, `session.py`, `drag.py`,
  `hittest.py`, `actions.py`, `allocation.py`, `permissions.py`, `presenter.py`
- `src/yasuki_gui/visuals/`, `ui/`: sprites and zone rendering, dialogs and the deck builder
- `src/yasuki_gui/layout.py`, `theme.py`, `constants.py`, `config.py`

## What it does

The client builds a table from a deck, drives the engine, and draws the redacted view it gets back.
It runs in two modes: the shipped rules session, where the engine offers legal actions and refuses
everything else, and a local sandbox over the manual intent surface, where anything is allowed. A
feature written against one mode needs deciding for the other.

Rendering and card manipulation are hot paths: no redundant checks, no work inside a loop that could
be hoisted, and exceptions propagate rather than being swallowed. A silently eaten error around a
state transition is a recurring source of bugs here.

## What checks it

- The suite: GUI tests mock Tk rather than running the main loop, so they run headless in CI
- `pixi run play`: the only way to see rendering and input actually work

## How it fits

`docs/design/tk-client.md` is the reference for the client's structure and its two modes, and
`docs/getting_started/running.md` covers running it, including the optional config file copied from
`config.yaml.example`.

The engine surfaces it drives are the `turns-and-actions` skill. It shares the setup pipeline and
the redaction contract with the web server, covered by `play-server`.
