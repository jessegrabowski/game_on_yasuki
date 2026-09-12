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

## The unfinished work

`GameState.stack` holds what is waiting, last in and first out. A cascade that pauses mid-list
stashes its remainder there as a {class}`~.ResumeCascade`:

```python
def _stash(
    game: GameState,
    effects: tuple[Effect, ...],
    firing: list[tuple[L5RCard, Trigger]],
    event: GameEvent | None,
    queue: list[GameEvent],
) -> None:
    remaining = tuple((card.id, trigger) for card, trigger in firing)
    game.stack.append(ResumeCascade(effects, remaining, event, tuple(queue)))
```

Everything the walk had in hand goes with it: the effects not yet committed, the triggers not yet
fired, the event being answered, and the events still queued. {func}`~.resume_cascade` splices the
answer's effects in where the paused one stood, ahead of all of that, and drops any trigger whose
card has left play in the meantime.

The work items in {mod}`~yasuki_core.engine.rules.vocabulary.work` are the other things that wait
the same way, mostly the middle of an action whose cost raised a question.
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
