# Decisions and resumption

Some effects cannot finish alone. "Choose a Personality" has no answer until a seat gives one, so
the engine stops, records the question, and hands control back. This page is what happens in
between: where the question lives, where the unfinished work waits, and how the two meet again.

## The question

A {class}`~.DecisionRequest` is a frozen dataclass naming the seat that must answer and the ids it
may answer with:

```python
seat: PlayerId
candidates: tuple[str, ...]

@abstractmethod
def accepts(self, response: DecisionResponse) -> bool:
    """Return whether ``response`` is a structurally well-formed answer to this request — the
    right shape, drawn from ``candidates``. A well-formed answer may still be illegal
    against the game state; the rules layer makes that check separately."""
```

The concrete requests form a closed union that grows with the rules vocabulary.
{meth}`~.DecisionRequest.accepts` is the line to read twice, because it checks shape and not
legality. A response naming a card outside `candidates` is malformed and refused here. A response
naming a card that is in `candidates` but has since become an illegal target is well formed, and
the rules layer is what turns it down.

The engine puts the request on `GameState.pending` and returns. Nothing polls, and nothing blocks.

## The life of a decision

A decision is raised, answered, cleared and resumed, in that order, and four rules say who may do
each. They exist because a question can be lost without anything failing: a handler that clears
`pending` at the wrong moment, or a cascade driven over an open question, wipes the request one
line after it was set, and the game goes on as if nobody had asked. That is how
{card}`Spearmen of the Akasha` shipped doing nothing for months. Its offer was raised by the
end-of-turn discard, cleared by the handler that ran the discard, and the turn passed.

1. **One owner.** `pending` is set wherever the engine genuinely stops to ask, and cleared only by
   {func}`~.submit` and {func}`~.cancel`, once, before a handler runs. No handler clears it. The
   `pending-owner` pre-commit hook refuses a `game.pending = None` anywhere else.
2. **One way to continue.** Anything that must happen after a cascade settles is a
   {class}`~yasuki_core.engine.rules.vocabulary.work.WorkItem` on `GameState.stack`. Nothing calls
   the next step directly after driving one.
3. **One instant, one cascade.** Occurrences that happen at the same moment are announced together
   with {func}`~.fire_all`. A loop over {func}`~.fire` says they happened one after another, and
   the second call would start a fresh walk over the first one's question.
4. **Violations are loud.** Driving a cascade while a decision is pending raises, naming the driver
   and the request.

{func}`~.submit` is where the first rule lives. It validates the answer's shape, clears the
request, and only then dispatches:

```{literalinclude} ../../../src/yasuki_core/engine/rules/turn/action_sequence.py
:start-at: request = game.pending
:end-at: game.pending = None
:dedent: 4
:language: python
```

Clearing first is the whole point. A handler may raise a question of its own, and the request it
sets has to be the one pending when `submit` returns. Every arm after the clear runs on an empty
slot, and the tail is the same for all of them:

```{literalinclude} ../../../src/yasuki_core/engine/rules/turn/action_sequence.py
:start-at: Symmetric with `perform`: an answered decision
:end-at: yield_after_action(game, acted_in)
:dedent: 4
:language: python
```

The drain is the second rule. Whatever the answer queued runs now, unless one of those items
pauses again, and then the next answer picks it up. The yield is why a question asked by turn
structure needs no special case: the end-of-turn discard and the turn's opening resolve into a
round that did not exist when they were asked, and `yield_after_action` hands nothing on when the
round has changed under it.

An answer a handler rejects part-way through would leave the request cleared and the board
wherever the handler stopped. {meth}`EngineSession.submit <yasuki_core.engine.session.EngineSession.submit>`
rebuilds the game from the tape before the error propagates, which holds only accepted inputs, so
the question is asked again on the board it was first asked on. {func}`~.cancel` is the second,
narrower owner of the clear. It exists for replaying tapes that hold a `Cancel`, and it clears
after its undo, so a refused cancel leaves the question in place.

## The unfinished work

`GameState.stack` holds what is waiting, last in and first out. A cascade that pauses mid-list
stashes its remainder there as a {class}`~.ResumeCascade`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _stash
:language: python
```

Everything the walk had in hand goes with it: the effects not yet committed, the triggers not yet
fired, the event being answered, and the events still queued. {func}`~.resume_paused_cascade` pops
that stash when a card choice is answered and splices the answer's effects in where the paused
one stood, ahead of all of that, dropping any trigger whose card has left play in the meantime.
The stash is always the top of the stack, because a choice pauses the walk the moment it is
raised and nothing pushes between the pause and the answer.

The other {class}`~yasuki_core.engine.rules.vocabulary.work.WorkItem` implementations, each
declared beside the procedure that pushes it, wait the same way, mostly the middle of an action
whose cost raised a question.
[Action lifecycles](action-lifecycles.md) covers those.

## Why a resolver is a string

A {class}`~.Choose` collects ids. Turning those ids into effects is a separate function, and the
effect names it rather than carrying it:

```python
# A choice resolver turns the ids a Choose collected into the effects the choice produces, given the
# seat that answered. Keyed by a string so a paused ChooseCards names its resolver, keeping the
# pending decision replay-stable (a stored closure would not rebuild to an equal object).
Resolver = Callable[..., list[Effect]]
CHOICE_RESOLVERS: dict[str, Resolver] = {}
```

A pending decision has to survive being written down and read back. A function object does not
compare equal to the one a replay rebuilds, so a request holding one would break the equality that
[The replay log](the-replay-log.md) rests on. A string does compare equal.

`@choice_resolver(key)` registers the function, and a key already taken raises rather than silently
replacing. Its optional `prompt` is fixed wording.
{meth}`ChooseCards.prompt <yasuki_core.engine.rules.vocabulary.decisions.ChooseCards.prompt>` reads
that and falls back to a generic line counting the cards, so a choice with no registered wording
still asks something. A request whose wording has to track the answer being built computes it
instead. {class}`~.ChoosePayment` reports the gold still owed after the producers named so far.

## Where a card plugs in

By returning a {class}`~.Choose` and registering the resolver that answers it.
[Asking the player a question](../../contributing/asking_a_question.md) is the five shapes in
order.
