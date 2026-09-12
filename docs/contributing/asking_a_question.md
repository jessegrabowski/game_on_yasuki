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

## A number

{class}`~.AskAmount` takes the amounts the seat may name. {card}`Hired Killer` asks how much Gold
to spend, and the answer decides what the card can reach:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/lotus_edition.py
:pyobject: _hired_killer_amounts
:language: python
```

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

## A mode

{class}`~.AskOption` offers a fixed set of answers that are not cards.
{card}`Courts of Otosan Uchi` asks two questions in a row, naming a player and then a direction,
and carries the first answer into the second:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_otosan_uchi.py
:pyobject: _resolve_courts_of_otosan_uchi_player
:language: python
```

`resolver_context` is how a chained question remembers. The second resolver declares it as a
keyword parameter, and only a resolver whose card supplies one needs to.

## How many go where

{class}`~.AskDistribution` hands out several things among several recipients.
{card}`Suiteiru no Oni` deals Oni Followers among a seat's Personalities:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/promotional_diamond.py
:pyobject: _suiteiru_no_oni_effects
:language: python
```

A recipient named twice gets two.

## Two rules that catch people

**Return nothing rather than an empty question.** Every shape takes the candidates it may be
answered with, and a question with none of them is not a question. Both Hired Killer and Ichiro
Yojimbo check first and return the rest of their effects, or no effects at all.

**Register a prompt, and keep counts out of it.** Without one the seat is asked "Choose 1 card",
which says nothing about what the card is doing. Pass `prompt=` to `@choice_resolver`, as Ichiro
Yojimbo does. Leave the numbers to the client, which draws its own count and ticks it down as
the seat picks, because the same choice can offer one target or two.

## Where the rest lives

[Effects](../design/systems/effects.md) is the vocabulary a resolver returns.
[Reacting to an event](reacting_to_events.md) covers triggers, which is where Ichiro Yojimbo's
question comes from.
