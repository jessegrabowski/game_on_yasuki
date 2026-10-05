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

Any request that picks cards carries {class}`~.PickLimit` conditions on the set, which is how one
phrase naming several cards stays one question. A limit answers two questions, kept apart because
they come apart: {meth}`~.PickLimit.permits` says whether a card may still join what is picked, and
{meth}`~.PickLimit.satisfied` whether what is picked is a legal answer. A ceiling
({class}`~.TotalAtMost`) refuses the pick that would break it, so its two answers agree. A floor
refuses nothing and is unsatisfied until enough is picked, so they do not.
{meth}`~.DecisionRequest.selectable` reports what a part-built answer may still grow by -- every
candidate while nothing is picked, the rest of one part of a {class}`~.OneGroup` once something is
-- and a client reads it to gray out the board the first pick ruled out. The picks themselves stay
on offer, so clicking one again takes it back.

The limits are plain data, computed when the request is raised. They have to be: a pending request
is written to the tape and compared against the one a replay rebuilds, and a closure would not
compare equal. Nothing can move between the raising and the answer anyway, because the cascade is
paused on the question. A rule that cannot be said in data -- one reading the board as the answer is
built -- would need a named predicate in a registry, the way a choice resolver is named, rather than
a function on the request.

A limited question has to be answerable before it is asked, which takes two readings of the limits.
{func}`~.within_reach` drops a candidate no legal answer could hold at all, which is the one whose
own weight already breaks a ceiling, and it runs where the targets are read, so the offering, the
question and an Interrupt's substitution agree on what is targetable. {func}`~.answerable` then
asks whether what is left can seat the fewest cards the phrase takes: enough candidates, and every
limit able to admit that many ({meth}`~.PickLimit.admits`, the third question a limit answers). A
phrase that fails either withholds the action, and a later phrase that fails targets nothing. Three
Personalities of Force three are each a legal target of "two cards with total Force less than five"
and no two of them are, so that phrase is no action at all.

Each limit is asked on its own, so a phrase carrying two gets a necessary condition rather than a
sufficient one: both can admit the minimum over sets that do not overlap. Nothing prints two yet,
and the card that does wants a joint check instead.

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
   with {func}`~.fire_all`. A loop over {func}`~.fire` says they happened one after another, so
   their triggers would never be ordered together, and the second call would start a fresh walk
   over the first one's question.
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

Backing out is refused outright while `GameState.look` is set, whatever the request's own
`cancellable` says. A seat that has looked at the top of its deck has information it cannot give
back, so every question asked about those cards is committed the moment the look opened.

A request a trigger raised is refused the same way, whatever its `cancellable` says. A trigger
reacts to an event that has already happened, so its question has no action of its own to unwind,
and the tape's nearest action is one that already resolved. The cascade marks the request
`triggered` when it raises it on a trigger's behalf, and the mark follows the trigger's effects
through a stash. Declining is how a seat says no to a "may" question a trait asks.

A {class}`~.ChooseNextTrigger` is never backed out of either. It is the one decision whose seat is
not the controller of what it decides: the active player names which of an occurrence's triggers
resolves next, whoever's cards they are (CR, Timing Conflicts), and each trigger's own questions
then go to its controller. It is asked whenever two or more triggers would act, on one card or
several, and then once for each of them, even when every order leads to the same board, such as two
Rice Farms each taking a token as a turn begins. Its answer names one trigger. A trigger its text
makes optional asks that of its own controller once it resolves.
The CR gives the order to the active player without exception, so the engine does not judge which
orders matter, and each such conflict is a decision point in every game the bots play.

A request whose `reopens_on_cancel` is true backs out one decision instead of unwinding the
action: the tape loses only the answer that raised it, and the question before it comes back on
replay. An Interrupt is an action of its own on the tape, so backing out of any question it asks,
which effect, its target, its adjustment or its payment, unwinds the Interrupt and leaves the
interrupted action held beneath the step, where it belongs to whoever announced it.

## The unfinished work

`GameState.stack` holds what is waiting, last in and first out. A cascade that pauses mid-list
stashes its remainder there as a {class}`~.ResumeCascade`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/triggers.py
:pyobject: _stash
:language: python
```

Everything the walk had in hand goes with it, as the stack of frames it was walking: the effects not
yet committed and the provenance they carry, the triggers not yet fired, the event being answered,
and the events still queued. {func}`~.resume_paused_cascade` pops that stash when a card choice is
answered and splices the answer's effects into the top frame, where the paused one stood, ahead of
the rest of that frame and every frame beneath it, dropping any trigger whose card has left play in
the meantime.
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
