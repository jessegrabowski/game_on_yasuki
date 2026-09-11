# Writing an ability

An ability is four things: when it may be taken, what it costs, what it may be pointed at, and what
it does. {card}`Dull Tanto` is the whole of a simple one.

```python
def _dull_tanto_targets(game: GameState, source: L5RCard) -> list[str]:
    """Every Personality on the board. The card says "a target Personality" and narrows it no
    further, so the controller's own are legal targets."""
    return [card.id for card in personalities_in_play(game)]


def _dull_tanto_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Two -1F tokens on the target, then destroy this Item. Two separate tokens rather than one
    worth -2F, so an effect that removes a single token removes only 1 Force."""
    return [
        AdjustCounter(target.id, MINUS_1F, 2),
        Destroy(source.id, source.owner),
    ]


register_ability(
    "dull_tanto",
    Ability(
        timings=(ActionTiming.OPEN,),
        label="Open: give a Personality two -1F tokens and destroy this Item",
        cost=no_cost,
        targets=_dull_tanto_targets,
        effects=_dull_tanto_effects,
    ),
)
```

Four parts, in the order the dataclass lists them.

## Timing

`timings` is a tuple, because a card can print two designators and the ability may be used in any
round that permits either. `OPEN` here means the Action Phase, available to any player.

The designator names a window. Whether that window is open right now is not the card's business,
and [The turn machine](../design/systems/turn-flow.md) covers what opens it.

## Cost

`cost` maps the game and the source card to the effects that paying produces, so bowing, destroying
and spending a token are all written the same way.

Dull Tanto uses `no_cost`. The card destroys itself, but that is part of what the ability *does*,
not what it costs, so it sits in `effects`.

## Targets

`targets` returns the ids the ability may be pointed at, and an empty list means it cannot be
offered at all. That is how a card with nothing to target stays off the menu instead of appearing
and failing.

Dull Tanto targets every Personality on the board. The card says "a target Personality" and
narrows it no further, so the controller's own are legal. Write what the card says.

**What you return is not final.** `legal_targets` narrows it by the Rules of Location before the
ability is offered, so write the predicate for the card's text and stop there. Reimplementing
those rules in a handler, or working around them, both produce a card that is wrong in a way no
test catches. [Actions and legality](../design/systems/actions-and-legality.md) covers why the
narrowing is central.

## Effects

`effects` maps the game, the source and one chosen target to what happens. It returns effects and
mutates nothing.

Dull Tanto's second docstring is a modeling decision worth copying: two separate -1F tokens rather
than one worth -2F, so that an effect removing a single token removes only 1 Force. The printed
card does not say which, and the finer grain is the one that behaves correctly under everything
else in the vocabulary.

## Where the rest lives

[Abilities and costs](../design/systems/abilities-and-costs.md) covers the model and the cost
builders. [A card that prints two abilities](several_abilities.md) covers keys.
