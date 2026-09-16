# Writing an ability

```{card-image} Dull Tanto
:printing: road_to_ruin
:width: 220px
```

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

### How long it lasts

An effect that changes a card, such as `GrantModifier` or `GrantKeyword`, carries a
{class}`~yasuki_core.engine.rules.vocabulary.modifiers.Duration`, and the card usually prints none.
The Comprehensive Rules fill the gap: an ongoing effect lasts until the end of the current turn
unless the card gives a different duration (CR, Duration of Effects). So a bare "give" is
`Duration.UNTIL_END_OF_TURN`, and only a card that says so reaches for `PERMANENT` or
`WHILE_SOURCE_IN_PLAY`. {card}`Chuda Jomei` on [Adding a Card](adding_a_card.md) is a keyword
grant written that way.

Bowing, tokens and Family Honor have no duration at all. They are instantaneous changes that stay
until something else changes them (CR, Instantaneous), which is why `AdjustCounter` and
`GainHonor` take none.

A Honor gain that an action or trait earns by targeting a Personality, or from one, names him in
`GainHonor.personalities`. While he is dishonorable and the gaining seat's, the effect rehonors him
in place of the gain (CR, Rehonoring 0.1 and 0.2). {card}`Blessed Sword` names its bearer this
way. Leave the field empty when the ability rehonors him as one of its own effects, since the CR
substitutes only where rehonoring "is not one of that action or trait's effects".

### Who it reaches

`GrantModifier` names one target, and most cards do too: "give a target Personality +2F". Some
name a condition instead. {card}`Flashy Technique` reads *"Open: If you have not played another
Flashy Technique this turn, Personalities have -1F while attacking."* There is no target to choose,
and the Personalities it means are whichever ones are attacking whenever Force is read, including
one Recruited after the card was played. That is `GrantConditionalModifier`, which carries a
{class}`~yasuki_core.engine.rules.vocabulary.modifiers.Condition` where `GrantModifier` carries a
target id:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/the_harbinger.py
:pyobject: _flashy_technique_effects
:language: python
```

The card's two clauses are different kinds of thing, and the handler keeps them apart. The
handler checks "if you have not played another this turn" once, when the action resolves, and the
action stays legal when that fails and does nothing. The handler never checks "while attacking".
That clause is the condition the record carries, and the read path asks it of each Personality on
every read.

A condition the enum does not have yet is added in
`src/yasuki_core/engine/rules/stats/conditions.py`, next to the one that is there.
[Stats: printed against effective](../design/systems/stats.md) shows the read side.

## Where the rest lives

[Abilities and costs](../design/systems/abilities-and-costs.md) covers the model and the cost
builders. [A card that prints two abilities](several_abilities.md) covers keys.
