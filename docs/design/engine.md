# Core engine design

The rules engine lives in `yasuki_core.engine`. It is a pure, in-memory state machine: it holds the
table state, accepts intents, validates and applies them through the rules layer, and emits a log
plus redacted per-player views. It has no knowledge of the database, the web server, or the desktop
client. Those consume it.

## Two surfaces over one board

{class}`~.TableState`, the `ops` mutators and `redact` are the shared substrate. Two surfaces sit
on it and neither knows about the other.

The **manual intent surface** ({func}`~.apply_intent`) is free-form. A seat says "move this card
there" and the engine does it, checking ownership and little else. The web server and the GUI
sandbox drive it.

The **rules surface** ({class}`~.EngineSession`) is turn-structured. A seat takes an action the
rules offer, and the engine runs the turn machine, the cascade and the decisions. The shipped GUI
drives it.

Both mutate through the same `ops` and neither ships unredacted state.

## The pieces

- **Table state** (`engine/table.py`, `engine/players.py`, `engine/zones.py`) is the authoritative
  game state: players, their zones, and the cards in them.
- **Sessions and intents** (`engine/session.py`, `engine/intents.py`, `engine/intent_handlers.py`,
  `engine/ops.py`) hold the intent vocabulary, the interpreter that applies it, and how an action is
  requested, validated and applied as a state transition.
- **The rules layer** (`engine/rules/`) holds everything the systems pages below describe.
- **Redaction** (`engine/redaction.py`) produces the per-player views clients are allowed to see.
- **Replay** (`engine/replay/`) holds the wire codec, the initial position a tape replays from, and
  the two tapes: `intent_log.py` for the manual surface and `game_log.py` for the rules one.

## The systems

Each page explains one system, what problem it solves, and where a card plugs into it.

[GameState](systems/game-state.md) is the object every card function receives.
[Board queries](systems/board-queries.md) is how to ask the board a question.

[Effects](systems/effects.md) is the contract a card's return value answers to, and
[Triggers and the cascade](systems/triggers-and-the-cascade.md) is the loop that commits them.
[Decisions and resumption](systems/decisions-and-resumption.md) is what happens when an effect has
to stop and ask, and [The replay log](systems/the-replay-log.md) is why it stops the way it does.

[Abilities and costs](systems/abilities-and-costs.md) is the four parts a card declares.
[The turn machine](systems/turn-flow.md) opens the windows those declarations name,
[Actions and legality](systems/actions-and-legality.md) decides what a seat may take in one, and
[Action lifecycles](systems/action-lifecycles.md) is what runs between announcing and resolving.

[Stats](systems/stats.md) is the `effective_*` read path, and [Gold](systems/gold.md) is production
and payment. [Units and attachments](systems/units-and-attachments.md) is the unit relation,
[Battle](systems/battle.md) is the fighting, and
[The Imperial Favor](systems/the-imperial-favor.md) is the Favor and Lobby.

[Registration and the audit](systems/registration-and-the-audit.md) is how a card's id binds to its
code. [Bots and policies](systems/bots-and-policies.md) is the tail a new card has.

## The boundaries

[Package boundaries](package_boundaries.md) states the dependency rules this layer holds to and
which of them anything enforces. [Card vocabulary](card_vocabulary.md) is the closed set of data
types a card's behavior is expressed in.

To write a card rather than read about one, start at
[Adding a card](../contributing/adding_a_card.md).
