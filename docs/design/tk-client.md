# Tkinter client architecture

The desktop client (`yasuki_gui`) is a Tkinter application that renders the game board and drives the
same `yasuki_core` engine locally. Rendering is separated from interaction: `FieldView` draws the board
and its sprites, while `Controller` translates user input into engine intents.

```{note}
This page is an outline. The full write-up is still being written; the bullets below are the intended
sections.
```

The pieces, at a glance:

- **Rendering** (`field_view.py`, `visuals/`) draws the board, zones, card sprites, and hand.
- **Interaction** (`controller.py`, `services/`) covers hotkeys, drag-and-drop, hit-testing, and
  the action permissions that gate what a player may do.
- **Session** (`session.py`, `rules_runner.py`) builds table state from a deck and runs the engine
  behind the UI.
- **Deck builder** (`ui/deck_builder/`) is the in-client deck editor.

To be documented here:

- The render/interaction split and why it exists.
- How a drag gesture becomes an engine intent.
- How the client consumes engine snapshots and redacted state.

## Panels float over the board

A panel that shows a procedure is a {class}`~.FloatingPanel` placed over the board rather than a
region beside it: {class}`~.BattleView` for an attack, {class}`~.DuelPanel` for a duel,
{class}`~.LookView` for the cards a look shows, and {class}`~.CardStrip` for any pile a player opens.
Each one opens at a starting place the window computes and then stays wherever the player has dragged
it, so the geometry is a first-open default and not a dock.

A panel that draws cards subclasses {class}`~.CardPanel`, which gives it the sprite cache, hit
testing and `card_under_pointer`. Two things have to be registered for a new panel to behave like the
others. `GameWindow._card_panels` is the list the view key walks, topmost first, before falling back
to the board, and a panel left out of it answers correctly while nothing asks. The enlarged card is
one {class}`~.CardPreview` owned by the window and drawn on the root, so no panel can clip or hide
another's.

## Where an option goes

An option belongs on the thing that produces or consumes it, so the player picks a card by pointing
at the card. A card's own choices are on its left-click menu, built by
{meth}`~.Presenter.on_card_activated`; a deck's are on the deck cell in the seat's info box, through
{meth}`~.Presenter.on_deck_activated`; a battlefield's are on its lane in the battle panel.

{class}`~.PromptBox` takes answers shaped like yes, no, pass, or one of a few outcomes a card spells
out in words. It is not a place to list cards. A decision whose candidates are cards or card sources
is offered where those cards are drawn, and the prompt box keeps only what is left over. A duel is
the worked example: `FocusOrStrike` offers one focus per hand card and one on the Fate deck, and the
prompt box carries the strike alone.

The board's selection mode is the third surface, for a decision answered by picking cards already in
play. A decision whose candidates are not card ids must never reach it. `begin_selection` matches
candidates against card ids, so a request carrying anything else highlights nothing and strands the
player on a prompt that cannot be answered.
