# Asking the player a question

```{card-image} Ichiro Yojimbo
:printing: code_of_bushido
:width: 220px
```

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

```python
def _hired_killer_amounts(game: GameState, source: L5RCard) -> tuple[int, ...]:
    if not personalities_in_play(game):
        return ()
    return tuple(range(reachable_gold(game, source.owner) + 1))
```

An empty tuple means the question cannot be asked, and an ability whose cost cannot be paid is
never offered.

## A card

{class}`~.Choose` collects ids. {card}`Ichiro Yojimbo` creates a second Follower and lets its
controller pick who carries it:

```python
return [Choose(ctx.card.owner, targets, 1, 1, "ichiro_yojimbo", ctx.card.id)]


@choice_resolver(
    "ichiro_yojimbo", prompt="Attach the created Follower to one of your Personalities"
)
def _resolve_ichiro_yojimbo(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [CreateToken(MEDIUM_FOLLOWER, seat, source_id, attach_to=chosen[0])]
```

The two numbers are the minimum and the maximum. The string is the resolver's name, and
`@choice_resolver` on the function is what makes the two meet.

## A mode

{class}`~.AskOption` offers a fixed set of answers that are not cards.
{card}`Courts of Otosan Uchi` asks two questions in a row, naming a player and then a direction,
and carries the first answer into the second:

```python
return [
    AskOption(
        seat,
        (COURTS_GAIN, COURTS_LOSE),
        f"Does {named} gain or lose {COURTS_HONOR} Honor?",
        "courts_of_otosan_uchi_swing",
        source_id,
        resolver_context=(picked.name,),
    )
]
```

`resolver_context` is how a chained question remembers. The second resolver declares it as a
keyword parameter, and only a resolver whose card supplies one needs to.

## How many go where

{class}`~.AskDistribution` hands out several things among several recipients.
{card}`Suiteiru no Oni` deals Oni Followers among a seat's Personalities:

```python
return [
    destroy,
    AskDistribution(source.owner, bearers, podlings, "suiteiru_no_oni", source.id),
]
```

A recipient named twice gets two.

## Two rules that catch people

**Return nothing rather than an empty question.** Every shape takes the candidates it may be
answered with, and a question with none of them is not a question. Both Hired Killer and Ichiro
Yojimbo check first and return the rest of their effects, or no effects at all.

**Register a prompt.** Without one the seat is asked "Choose 1 card", which says nothing about
what the card is doing. Pass `prompt=` to `@choice_resolver`, as Ichiro Yojimbo does.

## Where the rest lives

[Effects](../design/systems/effects.md) is the vocabulary a resolver returns.
[Reacting to an event](reacting_to_events.md) covers triggers, which is where Ichiro Yojimbo's
question comes from.
