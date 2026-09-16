# A card that prints two abilities

```{card-image} Incendiary Archers
:printing: ivory_edition
:width: 220px
```

A card printing one ability registers it and stops. A card printing two has to say which is which.

{card}`Incendiary Archers` prints both a Ranged attack and a Fear effect, and they are separate
abilities with separate costs:

```python
register_ability(
    "incendiary_archers",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, Bow: Ranged {INCENDIARY_ARCHERS_RANGED} Attack",
        cost=bow_cost,
        targets=attack_targets,
        effects=_incendiary_archers_ranged_effects,
        key="ranged",
    ),
)

register_ability(
    "incendiary_archers",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle: Fear {INCENDIARY_ARCHERS_FEAR}",
        cost=no_cost,
        targets=attack_targets,
        effects=_incendiary_archers_fear_effects,
        key="fear",
    ),
)
```

## Keys

`key` is what an action names when a seat takes one of them. Without it the engine could not tell
the seat's choice apart from its sibling, so a second unkeyed ability is refused:

```
incendiary_archers prints several abilities, so each one needs a key
```

Repeating a key already registered for the card is refused the same way. Both raise at import, so
the mistake surfaces when the module loads rather than mid-game.

## Both are offered, and each pays its own way

The two halves appear independently on the seat's menu. Taking one does not consume the other, and
each pays the cost it declares. Incendiary Archers shows that plainly: the Ranged attack costs a
bow and the Fear costs nothing, so a seat can take the Fear and still have an unbowed card.

## Naming the handlers

Two `effects` functions on one card would collide under the usual `_<card id>_<role>` convention,
so a card with keys puts the key in the name. `_incendiary_archers_ranged_effects` and
`_incendiary_archers_fear_effects` are the pattern, and the `card-layout` pre-commit hook checks
that the key in a name is one the module really registers.

## An ability a card is given

A card can come to hold a second ability without printing one. {card}`Daidoji Kaede` reads
*"Open: While a target Personality opposes Kaede (this turn), she has, 'Battle: Ranged 3.'"* The
Open is printed and the Ranged Attack is not. Her module registers the Open with `key="opposition"`
and a factory under `@granted_ability` that builds the Battle ability from the id the Open chose:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:pyobject: _daidoji_kaede_opposition_effects
:language: python
```

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:pyobject: _daidoji_kaede_granted_ability
:language: python
```

The rules on this page apply as soon as the grant is recorded. Kaede then holds two abilities, so
the printed Open needs a key of its own even though the card prints only one, and the granted
ability's "while" is its `targets` returning nothing when the named Personality is not opposing
her. `GrantAbility` is the effect, and [Abilities and costs](../design/systems/abilities-and-costs.md)
shows how `abilities_for` reads the record.

## Where the rest lives

[Abilities and costs](../design/systems/abilities-and-costs.md) covers the ability model.
[Writing an ability](an_ability.md) covers the four parts in order.
