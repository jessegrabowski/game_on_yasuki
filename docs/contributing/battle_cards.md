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

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _legion_of_the_khan_effects
:language: python
```

Ranged and Melee destroy what they reach. Fear bows it. The compared stat is Force unless the card
says otherwise.

## Changing an attack's strength

A card that alters attacks registers a handler instead of an ability. Every card in play is asked
about every attack, so the handler has to state its own reach:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _legion_of_the_khan_attack_strength
:language: python
```

Compare the two cards for "this Follower". Use {func}`~.shares_unit` for "cards in this unit".
Use neither for a card whose text covers the whole board. The handlers sum, and the total has no
floor, so taking more strength off an attack than it had leaves it reaching nothing.

## Reaching past the usual rules

A card that acts in a battle it is not present at, or from home, sets `battle_designators`.
[Battle](../design/systems/battle.md) covers the three designators and which of them any card
actually uses. `targets_any_location` and `located_at` sit beside it, and a Strategy played out of
hand needs the second.

## Assigning, and a card that cannot

A Personality moves to a battlefield when its seat assigns it in the Maneuvers Segment, and
{class}`~yasuki_core.engine.rules.vocabulary.game_events.Assigned` is the event a trait reads for
"after X assigns to a battlefield". {card}`Daidoji Kaede` answers it with a Force bonus:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/chaos_reigns_part_ii.py
:pyobject: _daidoji_kaede_assigned
:language: python
```

Her first sentence, *"Kaede cannot attack"*, is `register_cannot_attack("daidoji_kaede")`. The
Attacker's assignment then never offers her, and the Defender's still does, which is the only way
her trait ever fires.

## After the battle, if it went a certain way

A `DelayedEffect` held to `END_OF_BATTLE` resolves once the outcome is recorded, but it holds a
fixed effect. When what happens depends on how the battle went, the held effect is an `Evaluate`,
which calls a registered resolver on the board as it stands at that moment. {card}`Daidoji Tashiko`
reads *"Engage: After this battle's resolution, if it was at a Province and the Province was not
destroyed, gain 2 Honor."*:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/shattered_empire.py
:pyobject: _daidoji_tashiko_effects
:language: python
```

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/shattered_empire.py
:pyobject: _resolve_daidoji_tashiko
:language: python
```

The resolver reads `attack.battlefields[attack.current].outcome`, which {class}`~.AnnounceResolution` writes
before it releases the delayed effects and before it clears `attack.current`.

## Where the rest lives

[Cards that attach](attachments.md) is the attachment side, including the two bow costs.
[A card that prints two abilities](several_abilities.md) uses Incendiary Archers, which prints a
Ranged attack and a Fear.
