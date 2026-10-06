# Asking the player a question

A card that says "choose" or "may" needs an answer before it can finish. The card returns an effect
that asks, the engine pauses and puts the question to the seat, and a resolver you register turns
the answer into more effects.
[Decisions and resumption](../design/systems/decisions-and-resumption.md) is the machinery. This
page is the five shapes and which one to reach for.

## Yes or no

{class}`~.Ask` is the whole of "may". {card}`Refugees` offers its controller a Follower for two
Gold:

```python
Ask(
    controller,
    f"Pay {ASHIGARU_GOLD} Gold to create a 1F Ashigaru Follower and attach it to "
    f"{target.name}?",
    "refugees",
    subjects=(target.id,),
    source_id=source.id,
)
```

The offer is not made at all when the controller cannot pay, which is what "may pay" means for a
seat with no Gold. Withholding the question is often the correct reading of a card that offers
something.

A question a card in hand raises is private to its owner. `project` hands the pending decision
only to the seat it names, so a Ring offered from hand after its condition is met is never shown
to the opponent, who would otherwise learn the hand held it.

## A number

{class}`~.AskAmount` takes the amounts the seat may name. {card}`Hired Killer` asks how much Gold
to spend, and the answer decides what the card can reach:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/lotus_edition.py
:pyobject: _hired_killer_amounts
:language: python
```

An amount printed in the cost block, a :X:, is paid at step B and shapes the targets chosen at
step C (CR, Action Sequence). {func}`~.declare_amount` asks it, and its answer is charged and
recorded as the action's `amount_declared`. The ability sets `targets_after_cost`, so its
`targets` are read once the cost is paid, and they and its `effects` read `game.amount_declared`:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/lotus_edition.py
:pyobject: _hired_killer_targets
:language: python
```

What the card does then resolves as the action's own effects, which the Interrupt step offers and
a negation of the action reaches. A resolver that returned the destruction from inside the cost
would make it a payment, which neither reaches. A count of targets the amount buys, as
{card}`Bound in Blood`'s "half the Gold spent", is its `target_count`, which reads
`game.amount_declared` the same way.

## A card

```{card-image} Ichiro Yojimbo
:printing: code_of_bushido
:width: 220px
```

{class}`~.Choose` collects ids. {card}`Ichiro Yojimbo` creates a second Follower and lets its
controller pick who carries it:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/code_of_bushido.py
:pyobject: _ichiro_yojimbo_entered_play
:language: python
```

The candidates are worked out first, and an empty list ends it there. The two numbers after them
are the minimum and the maximum. The string names the resolver, which turns the answer into
effects:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/code_of_bushido.py
:pyobject: _resolve_ichiro_yojimbo
:language: python
```

`@choice_resolver` on that function binds the two.

A minimum of zero makes the choice a "may". Where the cards are shown in a window of their own,
as a look at the top of a deck is, the client offers what picking a card does on the card itself,
and Done answers with whatever has been picked, nothing included. `@choice_resolver` takes that
wording as `pick`, as in `pick="Put on the bottom of your deck"`, and a choice that registers none
offers "Choose".

## A set the card puts a condition on

Some text picks several cards at once and says something about the set: "one or two of your target
cards in one unit", "one or two target Personalities with total Force less than Zaiberu's", "one to
two enemy Followers ... with total Gold Cost less than your Personality's". The count is the easy
half. The condition is a {class}`~.PickLimit`, and it answers two questions:

- {meth}`~.PickLimit.permits` says whether a card may still join what is picked, which is what
  narrows the board as the seat clicks.
- {meth}`~.PickLimit.satisfied` says whether what is picked is a legal answer, which is what lights
  the confirm button.

A ceiling refuses the pick that would break it, so its two answers agree. A floor refuses nothing
and stays unsatisfied until enough is picked, so they do not. Two limits ship:
{class}`~.OneGroup`, every pick from one part of a partition, and {class}`~.TotalAtMost`, the picks
weighing no more than a bound between them. A phrase may carry several, and all of them have to
hold.

A limit is plain data worked out when the question is raised, never a closure: a pending request has
to compare equal to the one a replay rebuilds. Nothing can move in between anyway, since the cascade
is paused on the question.

Where the cards are the action's own targets, the limits belong on the ability's
{class}`~.TargetGroup`, and the chosen cards are recorded as the action's targets. {card}`Ring of
Air` straightens "one or two of your target cards in one unit":

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/shattered_empire.py
:pyobject: _ring_of_air_limits
:language: python
```

A card no legal answer could hold is not offered at all -- one whose own Force already breaks a
total the set may not exceed cannot be targeted even alone -- and a phrase with no legal answer to
give withholds the action, which is what makes {card}`With Regards`' "two or more of your unbowed
Merchant or Ninja Personalities" no action for a seat with one, and a phrase taking two cards under
a total no two of them reach no action either. A limit says which sets it could ever admit through
{meth}`~.PickLimit.admits`, so neither the seat nor a bot is handed a question it cannot answer.

## A second phrase that reads the first

An ability printing two "target" phrases declares a {class}`~.TargetGroup` each, in print order,
and a later group is handed the picks already made. {card}`Desperate Melee` reads "Target your
Personality. Target and destroy one to two enemy Followers, or one to five enemy Followers if your
Personality is a Berserker, with total Gold Cost less than your Personality's", so its second
phrase reads the first for both its count and its ceiling:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/road_to_ruin.py
:pyobject: _desperate_melee_count
:language: python
```

Where the figure the first phrase settles narrows what the second may be pointed at, rather than
limiting a set, it belongs in that group's candidates instead. {card}`With Regards` destroys "a
target Personality with a lower Gold Cost than the combined Chi of your Personalities this
targeted":

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_iii.py
:pyobject: _with_regards_victims
:language: python
```

Such an ability builds its effects over the whole set with `effects_for_groups`, which is handed one
tuple of cards per phrase: effects built per target could not tell the phrases apart. Backing out of
a later phrase returns to the one before it, since targeting has changed nothing on the board.

## A mode

{class}`~.AskOption` offers a fixed set of answers that are not cards. "A target player gains or
loses N Honor" is two questions in a row, naming a player and then a direction, and enough cards
print it that {func}`~.ask_whose_honor_moves` asks them for all of them. {card}`Courts of Otosan
Uchi` and {card}`Inexplicable Challenge` each call it. Its first resolver carries the first answer
into the second:

```{literalinclude} ../../src/yasuki_core/engine/rules/abilities/idioms.py
:pyobject: _resolve_honor_swing_player
:language: python
```

`resolver_context` is how a chained question remembers. The second resolver declares it as a
keyword parameter, and only a resolver whose card supplies one needs to. When the card fixes the
direction, as in "a target player loses 3 Honor", {func}`~.ask_who_loses_honor` asks the one
question that is left. {card}`Hungry Moon` and {card}`Bayushi Gihei` call it.

## A card, or an answer that is not one

Where one half of a text is a card and the other is not, {class}`~.Choose` takes both at once.
Its `options` are the answers that are not cards, and the seat names one thing: a candidate, or
an option. {card}`Tamori Tsushima` puts a Ring from hand into play or creates a Yojimbo instead:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/onyx_edition.py
:pyobject: _tamori_tsushima_effects
:language: python
```

One resolver answers both, because the answer is one name either way. The client offers each
candidate on the card itself and each option on a button, so the board never enters selection mode
and there is nothing to confirm. Register a `pick=` alongside the `prompt=`, since the pick is what
words the entry on the card.

A question may be all options and no candidates. {card}`Honor Your Oaths` offers its Yojimbo as
cards and the Imperial Favor as an option. A seat holding the Favor with no Yojimbo to bow is asked
with an empty `candidates`, because an option is an answer of its own.

Do not ask the mode first where one of the modes is a card the seat can point at. That asks twice
for one decision, and the second question repeats what the first already settled.

## How many go where

{class}`~.AskDistribution` hands out several things among several recipients.
{card}`Suiteiru no Oni` deals Oni Followers among a seat's Personalities:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/promotional_diamond.py
:pyobject: _suiteiru_no_oni_effects
:language: python
```

A recipient named twice gets two.

## An order

{class}`~.Arrange` asks the seat to put cards in an order, for "put the rest back in any order".
{card}`Banish All Doubt` looks at four, puts one in hand, and puts the other three on the bottom:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/the_harbinger.py
:pyobject: _resolve_banish_all_doubt
:language: python
```

The resolver it names, `PUT_ON_BOTTOM`, is the rulebook's, so the card writes none of its own. The
answer comes back in the order the seat placed the cards, first placed first, and
{class}`~.PlaceOnDeck` puts the last one outermost. [Looking at cards](../design/systems/looking-at-cards.md)
has the whole shape, including the look the cards sit in while the questions are asked.

## Two rules that catch people

**Return nothing rather than an empty question.** Every shape takes the candidates it may be
answered with, and a question with none of them is not a question. Ichiro Yojimbo checks first and
returns the rest of its effects, or no effects at all.

**Register a prompt, and keep counts out of it.** Without one the seat is asked "Choose 1 card",
which says nothing about what the card is doing. Pass `prompt=` to `@choice_resolver`, as Ichiro
Yojimbo does. Leave the numbers to the client, which draws its own count and ticks it down as
the seat picks, because the same choice can offer one target or two.

## Where the rest lives

[Effects](../design/systems/effects.md) is the vocabulary a resolver returns.
[Reacting to an event](reacting_to_events.md) covers triggers, which is where Ichiro Yojimbo's
question comes from.
