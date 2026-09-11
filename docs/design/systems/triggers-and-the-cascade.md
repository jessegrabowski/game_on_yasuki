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

```python
@dataclass(frozen=True, slots=True)
class TriggerContext:
    """What a trigger reads: the live game, the card whose trigger is firing, and the event."""

    game: GameState
    card: L5RCard
    event: GameEvent
```

`game` is the live board, `card` is the copy whose trigger is firing, and `event` is what just
happened. A trigger takes one of these and returns a list of effects:

`rise_of_jigoku.py`:

```python
@on(EnteredPlay, "rural_market")
def _rural_market_entered_play(ctx: TriggerContext) -> list[Effect]:
    """After this Holding enters play, give it a +1GP Wealth token."""
    if ctx.event.card_id != ctx.card.id:
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]
```

It must not mutate anything. There is exactly one place the board changes,
{func}`~yasuki_core.engine.rules.triggers.apply_effect`:

```python
def apply_effect(game: GameState, effect: Effect) -> list[GameEvent]:
    """Commit one effect and return the events it raises, for the fixpoint walk to drain. This is
    the single mutation boundary; triggers themselves never mutate."""
    return effect.perform(game)

```

Everything a trigger wants to happen goes through the effects it returns, which is what lets the
engine order them, settle the rules between them, and replay the game from its inputs.

## Which copies react

A seat may control three copies of {card}`Rural Market`, all sharing a `printed_id`. Collection
walks the battlefield and gathers every trigger registered for the event, so all three fire and
each decides for itself whether the event was about it. `_collect`:

```python
def _collect(game: GameState, event: GameEvent) -> list[tuple[L5RCard, Trigger]]:
    by_id = _TRIGGERS.get(type(event))
    if not by_id:
        return []
    firing = [
        (card, trigger)
        for card in game.table.battlefield.cards
        for trigger in by_id.get(card.printed_id, ())
    ]
    # A departed card answers only for its own leaving, and for nothing that happens after.
    departed = _departed_subject(game, event)
    if departed is not None:
        firing.extend((departed, trigger) for trigger in by_id.get(departed.printed_id, ()))
    return firing
```

The `departed` branch is the carve-out that makes "after this card is destroyed" possible at all. A
card is already in a discard pile by the time its destruction is announced, so without it the card
would be gone before its own trigger could run.

{card}`Goju Kaxt` is the card that needs it. `torn_asunder.py`:

```python
@on(Destroyed, "goju_kaxt")
def _goju_kaxt_destroyed(ctx: TriggerContext) -> list[Effect]:
    """After this Follower is destroyed, a 4F/3C/0PH Ninja of his controller's Clan Alignment takes
    his place — the Follower announces his own death from the discard pile."""
    if ctx.event.card_id != ctx.card.id:
        return []
    seat = ctx.card.owner
    return [CreateToken(KAXT, seat, ctx.card.id, clan=seat_alignment_name(ctx.game, seat))]
```

The Follower announces his own death from the discard pile, and nothing else could announce it for
him. Thirty-four printed cards carry a clause of that shape, so this is a category rather than one
card's quirk.

Compare that guard with {card}`Rural Market`'s, which is written identically and means the
opposite. Rural Market reacts to *other* Farms dying, so `ctx.event.card_id != ctx.card.id`
excludes itself. Goju Kaxt reacts only to itself, so the same line requires itself. The event says
which card it is about, and what the trigger does with that is the whole difference.

The carve-out covers a card's own departure and nothing else. Everything after it is over for that
card, which is why a Personality killed on arrival does not go on to take his enter-play trait.

Order is fixed before anything fires, by `_canonical_order`:

```python
def _canonical_order(pair: tuple[L5RCard, Trigger]) -> tuple[str, str]:
    card = pair[0]
    return (card.owner.name if card.owner else "", card.id)

```

Owner then card id. Two cards reacting to the same event resolve the same way every time, which
replay depends on.

## The walk

`_advance` is a worklist run to a fixpoint. The whole machine is its loop body:

```python
    while True:
        for index, effect in enumerate(effects):
            if isinstance(effect, InterruptingEffect):
                # Stash before asking for the request: the work stack is LIFO, and an effect whose
                # request queues its own work (a recruit queues its resolution) must have that work
                # run before the remainder of this cascade resumes.
                _stash(game, tuple(effects[index + 1 :]), firing, event, queue)
                game.pending = effect.request(game)
                return
            _trace.append(f"    {effect.describe()}")
            queue.extend(apply_effect(game, effect))
            _settle_state_based_actions(game, queue)
        effects = ()
        if firing:
            card, trigger = firing.pop(0)
            _trace.append(f"  {card.printed_id} ({card.id}) reacts")
            effects = tuple(trigger(TriggerContext(game, card, event)))
            continue
        if not queue:
            # The walk can be entered on a board something else already made illegal, and with
            # nothing to commit the per-effect check never runs. Judge it before returning.
            _settle_state_based_actions(game, queue)
            if not queue:
                return
        resolved += 1
        if resolved > _MAX_CASCADE:
            raise RuntimeError(
                f"trigger cascade did not converge after {_MAX_CASCADE} events:\n{_render_trace()}"
            )
        event = queue.pop(0)
        # Kept for the Response Step, which asks what the action it follows actually did.
        game.action_events.append(event)
        _trace.append(type(event).__name__)
        firing = _collect(game, event)
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

The effects after this one, the triggers not yet fired, the event being processed, and the queue
behind it. The order in the loop above matters: the stash happens *before* `effect.request` is
called, because the work stack is last-in-first-out and an effect whose request queues its own work
needs that work to run first.

When the seat answers, {func}`~yasuki_core.engine.rules.triggers.resume_cascade`
picks up exactly where it stopped:

```python
def resume_cascade(game: GameState, item: ResumeCascade, produced: list[Effect]) -> None:
    """Continue a cascade an interrupting effect paused, splicing ``produced`` (the effects the
    answer produced) in where that effect stood, ahead of the effects, triggers, and events the
    pause stashed. Triggers whose card has since left play are dropped."""
    firing = [
        (game.table.cards_by_id[card_id], trigger)
        for card_id, trigger in item.firing
        if card_id in game.table.cards_by_id
    ]
    _advance(game, tuple(produced) + item.effects, firing, item.event, list(item.queue))
```

The answer's effects splice in where the interrupting effect stood. Triggers whose card has left
play in the meantime are dropped, since a card off the battlefield reacts to nothing.

This is also why a paused decision names its resolver with a string rather than holding the
function. A stored closure would not rebuild to an equal object, and a pending decision has to
survive being written to a replay log and read back.

## Entry points

{func}`~yasuki_core.engine.rules.triggers.fire`:

```python
def fire(game: GameState, event: GameEvent) -> None:
    """Resolve ``event`` and the cascade it triggers, running the worklist to a fixpoint."""
    _advance(game, (), [], None, [event])

```

An empty walk with one event in the queue.
{func}`~yasuki_core.engine.rules.triggers.resolve_effects` is the same thing entered with
effects in hand instead.

## Writing a card that uses this

See [Reacting to events](../../contributing/reacting_to_events.md).
