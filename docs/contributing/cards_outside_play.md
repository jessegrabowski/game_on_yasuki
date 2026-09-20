# Cards that act from outside play

```{card-image} Sneak Attack
:printing: imperial_edition
:width: 220px
```

An ability is offered only when its card is where the ability says it must be. That is `located_at`,
and it defaults to the battlefield, which is right for almost every card. Three kinds of card need
something else.

## A Strategy acts from hand

{card}`Sneak Attack` is played out of hand, resolves, and is discarded. Announcing it does two
things and neither of them moves the card:

```python
game.stack.append(ResolveStrategy(card_id, ability_key))
game.pending = payment_request(
    game, seat, effective_gold_cost(game, card), card.name, target=card
)
```

The card stays in hand until the payment is answered, so backing out of the payment leaves it
there. Resolution stacks the discard before deferring the ability:

```{literalinclude} ../../src/yasuki_core/engine/rules/abilities/strategy.py
:start-at: game.stack.append(DiscardPlayed(card_id))
:end-at: defer_ability(game, card, ability)
:dedent: 4
:language: python
```

The stack is last in, first out, so the discard runs *after* the ability, whether the ability hits
every target at once or pauses to be pointed at one. A Strategy's own handler never discards the
card.

The ability itself is ordinary apart from one field:

```python
located_at=(CardLocation.HAND,),
```

## An Event acts from its Province

An Event sits face-up in a Province and puts itself into play from there. Every Event prints that
same action, so {func}`~.register_event_entry` builds it once instead of writing it out per card:

```python
register_event_entry("shadow_of_the_dark_god")
register_event_entry("impressment", timing=ActionTiming.DYNASTY)
```

That builds an ability whose whole effect is one line:

```python
def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [PutIntoPlay(source.id)]
```

`timing` defaults to `OPEN`, which most Events print. Nothing discards the card afterward, because
by then it is no longer where it was played from, and the Province it vacates refills when the
board settles.

## A Fate card that stays in play

Most Fate cards are played and discarded. Rings, Kata and Edicts reach the board and stay there.
Terrain does too, and is its own case, below.

There is no per-kind machinery for staying, and none is needed, because the rule asks where the
card ended up, not what kind it is:

```{literalinclude} ../../src/yasuki_core/engine/rules/abilities/strategy.py
:pyobject: discard_played
:language: python
```

So the handler says one thing and the discard takes care of itself:

```python
return [PutIntoPlay(source.id)]
```

Two kinds that look like they belong here do not. An **Ancestor** is a Fate type that attaches to a
Personality, so it is an attachment and [Cards that attach](attachments.md) covers it. A **Tattoo**
is a Strategy that grants a lasting ability and is then discarded like any other Strategy, so
nothing about it stays.

## One idiom for entering from hand

An Edict prints "Open: Put this Edict into play", a Kata prints the same with its own kind, and a
Ring with an action entry prints "Open: If X, put this Ring into play". Each is an ability taken
from hand, with nothing to pay, whose effect is the card entering. {func}`~.register_entry` builds
that ability, so registering one takes a line:

```python
register_entry("act_with_authority", clears=keywords.EDICT)
register_entry("way_of_the_crab_experienced", clears=keywords.EDICT, condition=plays_clan(ruleset.CRAB))
```

The parameters are the clauses a card can add to that sentence.

`condition` is the "If X": a callable over the game and the card that, when it returns False,
withholds the entry from `legal_actions` the way a missing target withholds any ability.
{func}`~.plays_clan` is the one the clan Edicts use.

`clears` is a keyword whose other holders the owner controls are discarded as the card enters. An
Edict clears `keywords.EDICT`, which is the rulebook's limit of one at a time restated on the card
(ShE datasheet, Edicts), and a Kata clears `keywords.KATA`:

```{literalinclude} ../../src/yasuki_core/engine/rules/abilities/idioms.py
:start-at: def cleared(
:end-before: def effects(
:dedent: 4
:language: python
```

`timing` is the designator, `OPEN` unless the card says otherwise, and a tuple for a card printing
"Open/Dynasty". `extra_effects` resolves after the card enters, for an entry that goes on to do
something else. `key` names the entry on a card that prints another ability beside it, which every
Ring does.

Show of Power, the one ShE-legal Kata, is not written because its other half is blocked on Fear
retargeting. When it is, its entry is `register_entry("show_of_power", clears=keywords.KATA)`.

## Terrain, which attaches to a battlefield

Terrain is by far the largest of these kinds and does not follow the pattern. A Terrain enters play
attached to a battlefield, not to a seat, so what it has to get along with is whatever Terrain is
already there. How that is handled is the card's own business and varies across the pool. Many
print an explicit "Destroy a Terrain" clause ahead of putting themselves into play, and many say
nothing of the kind. Nothing is implemented for Terrain yet, and the first one written has to
settle what a battlefield attachment is before it can settle anything else.

## Looking at the top of a deck

{card}`Beset from All Sides` is played from hand and looks at cards that stay in the deck. The
handler opens the look and asks the first question about it in one list:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _beset_from_all_sides_effects
:language: python
```

The resolver reads what is still in view and asks the next question, naming the rulebook's ending
so the card writes no resolver for it:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _resolve_beset_from_all_sides
:language: python
```

[Looking at cards](../design/systems/looking-at-cards.md) is the whole shape, including why the
look is state and why nothing can be backed out of once it opens.

## Where the rest lives

[Abilities and costs](../design/systems/abilities-and-costs.md) covers `located_at` alongside the
other optional fields, and [Action lifecycles](../design/systems/action-lifecycles.md) covers what
happens between announcing and resolving.
