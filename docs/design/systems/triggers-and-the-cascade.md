# Triggers and the cascade

A card never changes the board. It returns *effects*, and one function commits them. Committing an
effect raises *events*, events wake more triggers, and those triggers return more effects. That loop
is the cascade, and it is the engine's answer to "and then what happened".

Every piece of code below is from {mod}`yasuki_core.engine.rules.triggers`, and each block says
which symbol it is. Public symbols link to their API entry, which carries a source link. The
private helpers have no API entry, so they are named but not linked. Read them through the module
link above.

## What a trigger reads

{class}`~yasuki_core.engine.rules.triggers.TriggerContext`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: TriggerContext
:language: python
```

`game` is the live board, `card` is the copy whose trigger is firing, and `event` is what just
happened. A trigger takes one of these and returns a list of effects:

`rise_of_jigoku.py`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/rise_of_jigoku.py
:pyobject: _rural_market_entered_play
:language: python
```

It must not mutate anything. There is exactly one place the board changes,
{func}`~yasuki_core.engine.rules.triggers.apply_effect`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: apply_effect
:language: python
```

Everything a trigger wants to happen goes through the effects it returns, which is what lets the
engine order them, settle the rules between them, and replay the game from its inputs.

## Which copies react

A seat may control three copies of {card}`Rural Market`, all sharing a `printed_id`. Collection
walks the battlefield and gathers every trigger registered for the event, so all three fire and
each decides for itself whether the event was about it. `_collect`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _collect
:language: python
```

The `departed` branch is the carve-out that makes "after this card is destroyed" possible at all. A
card is already in a discard pile by the time its destruction is announced, so without it the card
would be gone before its own trigger could run.

{card}`Goju Kaxt` is the card that needs it. `torn_asunder.py`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/torn_asunder.py
:pyobject: _goju_kaxt_destroyed
:language: python
```

The Follower announces his own death from the discard pile, and nothing else could announce it for
him. Many printed cards carry a clause of that shape, so this is a category rather than one
card's quirk.

Compare that guard with {card}`Rural Market`'s, which is written identically and means the
opposite. Rural Market reacts to *other* Farms dying, so `ctx.event.card_id != ctx.card.id`
excludes itself. Goju Kaxt reacts only to itself, so the same line requires itself. The event says
which card it is about, and what the trigger does with that is the whole difference.

The carve-out covers a card's own departure and nothing else. Everything after it is over for that
card, which is why a Personality killed on arrival does not go on to take his enter-play trait.

Order is fixed before anything fires, by `_canonical_order`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _canonical_order
:language: python
```

Owner then card id. Two cards reacting to the same event resolve the same way every time, which
replay depends on.

## The walk

`_advance` is a worklist run to a fixpoint. The whole machine is its loop body:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:start-at: while True:
:end-at: firing = _collect(game, event)
:language: python
```

Three repeating steps. Apply the effects in hand, each committing at once with the events it raises
joining the queue. Fire the next trigger still waiting on the current event, whose effects become
the next effects in hand. Pop the next event and collect what answers it.

`_settle_state_based_actions` runs after every effect, not once at the end. That is the order the
Comprehensive Rules give, and it is why a Personality who dies as he arrives is dead before his
arrival is announced.

A trigger that re-emits the event that woke it would spin forever. The walk raises after 1,000
events and prints the last sixty steps, alternating events and the cards that reacted to them.
Sixty is usually enough to see the cycle.

## Pausing to ask

The first branch in that loop handles a pause. An
{class}`~yasuki_core.engine.rules.effects.InterruptingEffect` cannot resolve without an answer from
a player. {card}`Wheat Farm` is one: entering play, it offers its controller a choice of up to two
other Farms to give a token, and the cascade cannot go on until someone picks. The machine stops
and `_stash` stores everything still outstanding:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _stash
:language: python
```

The effects after this one, the triggers not yet fired, the event being processed, and the queue
behind it. The order in the loop above matters: the stash happens *before* `effect.request` is
called, because the work stack is last-in-first-out and an effect whose request queues its own work
needs that work to run first.

When the seat answers, {func}`~yasuki_core.engine.rules.triggers.resume_cascade`
picks up exactly where it stopped:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: resume_cascade
:language: python
```

The answer's effects splice in where the interrupting effect stood. Triggers whose card has left
play in the meantime are dropped, since a card off the battlefield reacts to nothing.

This is also why a paused decision names its resolver with a string rather than holding the
function. A stored closure would not rebuild to an equal object, and a pending decision has to
survive being written to a replay log and read back.

## Entry points

{func}`~yasuki_core.engine.rules.triggers.fire`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: fire
:language: python
```

An empty walk with one event in the queue.
{func}`~yasuki_core.engine.rules.triggers.resolve_effects` is the same thing entered with
effects in hand instead.

## Writing a card that uses this

See [Reacting to events](../../contributing/reacting_to_events.md).
