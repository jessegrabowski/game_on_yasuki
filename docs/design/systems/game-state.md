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

```{literalinclude} ../../../src/yasuki_core/engine/rules/state.py
:start-at: active_rules : dict mapping PlayerId to frozenset of VictoryRule
:end-at: the dict is held to nothing. Default empty.
:dedent: 4
:language: text
```

A card that exempts its controller from a loss condition drops a rule from that seat's set. It does
not set a flag somewhere for the loss check to consult.

The rules are checked at the moment the CR names for each. An Honor Victory is read off the Honor a
seat starts its turn with and a Dishonor loss off the Honor it ends its turn with, so both are
called by the turn flow at that boundary. An Enlightenment Victory is won "immediately" by a seat
controlling Rings of all five elements, so {func}`~.enlightenment` is a state-based action and
runs after every committed effect. A Ring whose text says it does not count registers through
`register_no_enlightenment`.

## What replay rebuilds

Most of the rest is ephemeral. `stack`, `ongoing`, `delayed`, `round_stack`, `responded`,
`created_by`, `tokens_created`, `attack`, `look`, `turn_events`, `conditions_holding`,
`announced_from_hand`, `asked_outside_action`, `action` and its companions are all rebuilt by re-running the tape rather than serialized. [The replay log](the-replay-log.md) covers why.

`pending` is the question the engine has stopped on, or None, and `stack` is the work waiting
behind it. Together they are the engine's whole notion of "part-way through". A client reads
`pending` to know who is asked and what they may answer, and `awaiting_decision` is the same
question as a boolean. Only {func}`~.submit` and {func}`~.cancel` clear it, and every cascade entry
point raises while it is set. [Decisions and resumption](decisions-and-resumption.md) is the
lifecycle. A card never reads it: a handler runs on a cleared slot, and the request it raises is
the one that will be pending when control returns.

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

`action_seat` is the seat that announced the action now resolving, and `action_targets` the cards
its abilities were pointed at, in order. Both are what a Response reads when its card says "if the
action was yours" or "if it targeted this Personality". `action_events` is what the action did, in
order, for a Response that asks "if it discarded a Fate card". What an Interrupt or a Response does
inside its own round is left out of it, since a Strategy played as an Interrupt to your opponent's
action is your doing and not the action's. `turn_events` is the same record for the whole turn,
steps included, and `ActionResolved` is on it once per action, so a card that counts what happened
this turn folds over it rather than asking the state to keep a count for it:
{func}`~.favor_actions_this_turn` is the one such fold. The action's keywords, such as Political, are not
stored: {func}`~.action_keywords` reads them off the ability's registration or off the ruleset for
a rulebook action.

## Where a card plugs in

By reading, never by writing. A handler returns effects and the cascade commits them, and
[Effects](effects.md) is that contract.
