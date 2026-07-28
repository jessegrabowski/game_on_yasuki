# Tkinter Client Architecture

The desktop client (`yasuki_gui`) is a Tkinter application that renders the game board and drives the
same `yasuki_core` engine locally. Rendering is separated from interaction: `FieldView` draws the board
and its sprites, while `Controller` translates user input into engine intents.

```{note}
This page is an outline. The full write-up is still being written; the bullets below are the intended
sections.
```

The pieces, at a glance:

- **Rendering** (`field_view.py`, `visuals/`) — the board, zones, card sprites, and hand.
- **Interaction** (`controller.py`, `services/`) — hotkeys, drag-and-drop, hit-testing, and the action
  permissions that gate what a player may do.
- **Session** (`session.py`, `rules_runner.py`) — building table state from a deck and running the
  engine behind the UI.
- **Deck builder** (`ui/deck_builder/`) — the in-client deck editor.

To be documented here:

- The render/interaction split and why it exists.
- How a drag gesture becomes an engine intent.
- How the client consumes engine snapshots and redacted state.
