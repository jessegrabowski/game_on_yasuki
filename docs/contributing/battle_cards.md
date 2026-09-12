# Cards that act in a battle

```{card-image} Exquisite Nagamaki of the Fox Clan
:printing: ivory_edition
:width: 220px
```

A Battle ability is an ordinary ability with an ordinary timing, and attachments carry most of
them. {card}`Exquisite Nagamaki of the Fox Clan` is an Item whose entire printed text is one:

```python
register_ability(
    "exquisite_nagamaki_of_the_fox_clan",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, Bow: Melee {NAGAMAKI_MELEE} Attack",
        cost=bow_cost,
        targets=attack_targets,
        effects=_exquisite_nagamaki_of_the_fox_clan_effects,
    ),
)
```

{func}`~.bow_cost` bows the Item, which is what the printed icon means on an attachment.
{func}`~.attack_targets` is the target predicate every attack card needs, and it returns nothing
outside a battle, so the
ability is not offered where there is nothing to hit.

## Making the attack

The three attacks take a strength, a target and a cause. That makes most attacking abilities one
line:

```python
def _legion_of_the_khan_effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [RangedAttack(KHAN_RANGED, target.id, source.owner)]
```

Ranged and Melee destroy what they reach. Fear bows it. The compared stat is Force unless the card
says otherwise.

## Changing an attack's strength

A card that alters attacks registers a handler instead of an ability. Every card in play is asked
about every attack, so the handler has to state its own reach:

```python
@attack_strength_against("legion_of_the_khan")
def _legion_of_the_khan_attack_strength(
    game: GameState, card: L5RCard, target: L5RCard, attack: AttackEffect
) -> int:
    """ "Targeting this Follower" — every kind of attack, but only the ones aimed at her."""
    return KHAN_ATTACK_PENALTY if target is card else 0
```

Compare the two cards for "this Follower". Use {func}`~.shares_unit` for "cards in this unit".
Use neither for a card whose text covers the whole board. The handlers sum, and the total has no
floor, so taking more strength off an attack than it had leaves it reaching nothing.

## Reaching past the usual rules

A card that acts in a battle it is not present at, or from home, sets `battle_designators`.
[Battle](../design/systems/battle.md) covers the three designators and which of them any card
actually uses. `targets_any_location` and `located_at` sit beside it, and a Strategy played out of
hand needs the second.

## Where the rest lives

[Cards that attach](attachments.md) is the attachment side, including the two bow costs.
[A card that prints two abilities](several_abilities.md) uses Incendiary Archers, which prints a
Ranged attack and a Fear.
