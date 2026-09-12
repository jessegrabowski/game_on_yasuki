# Reacting to events

A card whose text starts with "After" is a trigger. The engine announces what happened, your
function decides whether it cares, and it returns the effects that follow. It is the second-most
used hook in the card modules and the easiest place to start.

## The smallest trigger

```{card-image} Rice Farm
:printing: chaos_reigns_part_ii
:width: 220px
```

{card}`Rice Farm` reads *"This Holding will not have more than four Wealth tokens. After your
turn begins, give this Holding a +1GP Wealth token."* Two sentences, and the whole card is four
lines, in `src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py`:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:pyobject: _rice_farm_turn_started
:language: python
```

Read it against the card. `@on(TurnStarted, "rice_farm")` is "after your turn begins", keyed to the
card's database id. The guard is the rest of the text: `ctx.card.owner is not ctx.event.seat` is the
word *your*, because the event fires at the start of every turn including your opponent's, and
{func}`~yasuki_core.engine.rules.triggers.at_cap` is the first sentence, the four-token
ceiling. Then one effect.

Notice what the first sentence did **not** become. "Will not have more than four" is not a rule the
engine enforces somewhere central. It is a condition on this card's own trigger, because that is the
only thing that adds tokens to it.

## Every copy of the card reacts

A seat may control three Rice Farms. All three have the same `printed_id`, so when a turn begins,
all three triggers fire. Each one is handed its own `ctx.card`, and each has to work out whether the
event concerns it.

Rice Farm gets this for free, because it acts on itself and reads only its own owner. A card that
reacts to something happening *to itself* does not. {card}`Rural Market` is one, and the rest of
this page is from `src/yasuki_core/engine/rules/cards/rise_of_jigoku.py`:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_jigoku.py
:pyobject: _rural_market_entered_play
:language: python
```

`ctx.event.card_id != ctx.card.id` is the whole difference between "this Holding" and "a Holding".
Control three Rural Markets, leave the guard out, and all three take a token when any one of them
enters play. Nothing raises, no test you wrote
fails, and the card is quietly wrong. Write this guard first and then write the rest.

## One card, two events

```{card-image} Rural Market
:printing: rise_of_jigoku
:width: 220px
```

Rural Market reads *"After this Holding enters play, and after your Farm is destroyed, give this
Holding a +1GP Wealth token."* That is one sentence in English and two triggers in Python, because
they answer different events. The second carries three guards the card's wording does not spell
out:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_jigoku.py
:pyobject: _rural_market_destroyed
:language: python
```

Three guards, each one a word on the card. The first is not on the card at all: Rural Market is
itself a Farm, so it answers its own destruction, and a card in a discard pile cannot hold tokens.
The second is *your*. The third is *Farm*, read through
{func}`~yasuki_core.engine.rules.stats.keyword_grants.effective_keywords` rather than off the
print, because a card can be granted the keyword by something else in play.

That last point generalizes. Ask the board what a card is right now. Never read the printed value
when an `effective_*` function exists for it.

## What you can react to

Nine events:

- {class}`~yasuki_core.engine.rules.vocabulary.game_events.EnteredPlay`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.Destroyed`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.Straightened`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.CardDiscarded`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.CounterGained`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.Revealed`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.TurnStarted`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.ProducingGold`
- {class}`~yasuki_core.engine.rules.vocabulary.game_events.ProducedGold`

Each one carries the fields your guard reads, so follow the link for the event you want. If the
moment your card names is not one of them, it needs a new event in the engine, which is a core
change rather than a card change.

A card also answers its own `Destroyed` and `CardDiscarded` even though it has already left the
battlefield. Everything else only fires for cards in play.

## Returning effects, not changes

Your trigger returns effects. It never writes to the board.
{func}`~yasuki_core.engine.rules.triggers.apply_effect` is the only thing that changes
anything, which is what lets the engine apply effects in order, settle the rules between each one,
and replay the whole game from its inputs.

Returning an empty list is normal and is how a trigger declines. Most of the body of a real trigger
is deciding whether to.

For what happens after you return, including the order several cards react in and what happens when
an effect has to stop and ask a player a question, see
[Triggers and the cascade](../design/systems/triggers-and-the-cascade.md).

## Where it goes

In the module for the set that first printed the card, under a header naming the card, with every
function for that card in that one block. A pre-commit hook checks the layout on the modules your
commit touches. The full rules are in [Adding a Card](adding_a_card.md).
