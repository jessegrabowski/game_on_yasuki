# GameState

Every card function is handed a `GameState`, and it gets nothing else. The fields divide into two
kinds: what the game is, and what the engine is part-way through.

## The board and the turn

`table` is the shared board substrate, and [Board queries](board-queries.md) is how to ask it
questions. `active` is whose turn it is, `turn` counts them, `phase` says where in the turn, and
`round` is the Action Round open in that phase.

`gold` is each seat's transient pool. Gold produced while paying a cost stays there for further
costs in the same phase and is cleared when the phase ends, which is why a card cannot bank
production across phases.

`favor_holder` is the seat holding the Imperial Favor, or None.
[The Imperial Favor](the-imperial-favor.md) covers what reads it.

## Winning and losing

`winner`, `loser`, `win_reason` and `loss_reason` are set together by {meth}`~.GameState.win` and
{meth}`~.GameState.lose`. The reasons are worded for a player rather than for a log.

`active_rules` is the interesting one:

```text
active_rules : dict mapping PlayerId to frozenset of VictoryRule
    The ways each seat can win or lose. :meth:`start` fills it from :func:`~.rules_at_start`;
    dropping a rule from a seat's set afterwards excuses that seat alone, which is how a card
    reading "you will not lose, or be eliminated, by Dishonor" is expressed. A seat absent from
    the dict is held to nothing. Default empty.
```

A card that exempts its controller from a loss condition drops a rule from that seat's set. It does
not set a flag somewhere for the loss check to consult.

## What replay rebuilds

Most of the rest is ephemeral. `stack`, `ongoing`, `delayed`, `round_stack`, `responded`,
`created_by`, `tokens_created`, `attack`, `action` and its companions are all rebuilt by re-running
the tape rather than serialized. [The replay log](the-replay-log.md) covers why.

Ephemeral does not mean empty at rest. `ongoing` holds every continuous grant in force and its
order is load-bearing, since grants apply in creation order.

`rng` is the engine's only source of randomness, rebuilt from `seed`. A handler that wants a random
choice uses it. Anything else makes the tape a lie.

## The fields a card reads most

`created_by` records what made what, and {meth}`~.GameState.creations_of` reads it back.
[Cards that create cards](../../contributing/creating_cards.md) covers it.

`once_per` carries usage flags for once-per-turn and once-per-game abilities, keyed by a string the
caller picks.

`straighten_delayed` holds cards that may not straighten, with the turn the delay began, because
the prohibition lifts once its controller's next Action Phase has ended.

`action_is_favor` says the action now resolving paid a Favor cost. It is settled during payment
rather than at announcement, since an action with an alternate cost is a Favor action only when the
Favor is the half actually paid.

## Where a card plugs in

By reading, never by writing. A handler returns effects and the cascade commits them, and
[Effects](effects.md) is that contract.
