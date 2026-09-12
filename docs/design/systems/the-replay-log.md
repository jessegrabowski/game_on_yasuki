# The replay log

A game is a starting position and a tape of inputs. Everything else is derived, and re-running the
tape produces the same game state every time. That one property explains several engine decisions
a card author will otherwise meet as arbitrary rules.

## What is recorded

```python
initial: InitialRecord
first_player: PlayerId
seed: int = 0
entries: list[GameInput] = field(default_factory=list)
```

The dealt table, who goes first, the master RNG seed, and the ordered tape. An entry is an
{class}`~.Act`, a seat taking an action, or an {class}`~.Answer`, a seat responding to a pending
decision. There is no third kind, because no other input reaches the engine.

{func}`replay <yasuki_core.engine.replay.game_log.replay>` rebuilds the final state by running the
engine from the snapshot and feeding each entry in order. It raises `ValueError` when an entry
does not match what the engine expects at that point, so a desynced tape fails loudly instead of
producing a plausible wrong game. The save format, the replay format and the netcode are the same
tape.

## What is not recorded

Anything the tape can rebuild. `GameState.stack` is ephemeral and never serialized: replay
reconstructs the pending work by re-running the action that created it, which is cheaper than
writing it down and cannot drift from what the engine would have built.

The cascade trace is kept out of `GameState` entirely for a related reason:

```python
# The tail of the current walk, kept only to describe a cascade that fails to converge. Module-level
# and bounded rather than carried on GameState: the history is derived (replay regenerates it), and
# GameState compares by field, so storing it there would drag traces into every replay-equality
# assertion. A deque of this size holds several cycles of any loop a human would need to read.
```

`replay(log) == game` is the assertion that proves the tape is faithful, and a field holding a
human-readable account of how the game got here would make two identical games compare unequal.

## What this costs a card

Two things, and both look arbitrary until this page.

A choice resolver is registered under a string rather than passed as a function, because a pending
decision must compare equal to the one replay rebuilds and a closure does not.
[Decisions and resumption](decisions-and-resumption.md) has the detail.

A card draws randomness from {attr}`GameState.rng <yasuki_core.engine.rules.state.GameState.rng>`,
which replay rebuilds from the logged seed, and never from a generator of its own. No card module
imports `random` today. In practice a handler is given the game, the source card and the target, and
that is the whole world it gets.
