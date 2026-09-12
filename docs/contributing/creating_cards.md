# Cards that create cards

```{card-image} Culling Grounds
:printing: rise_of_otosan_uchi
:width: 220px
```

A created card is a real card. It is stamped from a template the deck load resolved, so its stats,
keywords and art come off a print rather than being spelled out where it is made. One effect does
all of it. [Effects](../design/systems/effects.md) covers where that effect sits in the vocabulary.

## The simple case

{card}`Culling Grounds` recruits a servant out of nothing:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_otosan_uchi.py
:pyobject: _culling_grounds_effects
:language: python
```

`EXPENDABLE_SERVANT` is a token id naming the template. The 0F/2C on the printed card is on that
template, not in this handler.

The third argument is the creating card, and it matters later.

## An ability that names no target

Culling Grounds targets nothing. An ability still needs a target list to be offered, so it takes
its own card:

```python
targets=itself,
hits_every_target=True,
```

{func}`~.itself` returns the source's id, and `hits_every_target` resolves against it without
asking the seat to pick the only card it could mean.

## Remembering what you made

`creator_id` is why the third argument exists. A card that speaks about its creation later reads
the relation instead of hunting the board:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_otosan_uchi.py
:pyobject: _culling_grounds_straightened
:language: python
```

{meth}`~.GameState.creations_of` gives the cards this one created that are still on the table,
oldest first. Cards it made and lost are already gone from the list.

The other half of that bargain is one line, because the card grants a permission and says nothing
about when taking it is worth it:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/rise_of_otosan_uchi.py
:start-at: register_may_remain_bowed("culling_grounds")
:end-at: register_may_remain_bowed("culling_grounds")
:language: python
```

That takes the Holding out of the turn-start straighten. Straightening announces itself either way,
whether the turn start or an effect did it, so the drawback above is an ordinary trigger.

## Fixing a variable stat

A template can print `*` where the creating card supplies the number. {card}`Mishime Sensei` makes
an Oni whose Force is the Chi of the Personality it consumed:

```python
CreateToken(
    MISHIMES_ONI,
    seat,
    sensei.id,
    stats=((Stat.FORCE, effective_chi(game, target)),),
    banish_at_turn_end=not destroyed,
)
```

`stats` replaces the stat on the print the created card presents, so the Oni genuinely has that
Force instead of carrying a modifier over a printed zero.

`banish_at_turn_end` is recorded when the card is made, because by the time the turn ends there is
nothing left to decide. Here it is the difference between sparing the Personality and not.

## Creating onto a Personality

`attach_to` names the Personality a created attachment arrives on, and creating-and-attaching is
one effect rather than two. A created card has no id until it exists, so there is nothing to attach
in a second step. A card that names a target Personality creates nothing when that Personality has
left play in the meantime.

Where an attachment may hang is judged against the template by {func}`~.may_attach_created`, since
the card does not exist yet to be asked.
[Cards that attach](attachments.md) covers the rules it answers to.

## Where the rest lives

[Asking the player a question](asking_a_question.md) covers the {class}`~.Choose` that picks who
carries a creation, which is how Ichiro Yojimbo and Suiteiru no Oni hand theirs out.
