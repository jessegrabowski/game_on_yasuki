# Units and attachments

A Personality and the cards attached to him are a unit. That is one relation, and almost everything
a card says about Followers, Items, Spells or "cards in this unit" is a question asked of it.

## One flat relation, owned by the substrate

`TableState.units` maps an attached card's id to its Personality's. The relation is flat, so there
is no chain to walk, and the rules layer reads it without keeping a copy:

```python
# The readers below are views over ``TableState.units`` — unit membership, not the presentation
# stacking in ``TableState.attachments``, which carries no rules meaning and which the rules layer
# must never read. The substrate owns the relation and keeps its invariants, so nothing here
# validates or mirrors it. A rules-layer copy would be a desync waiting to happen.


def attached_to(game: GameState, card: L5RCard) -> L5RCard | None:
    personality_id = game.table.units.get(card.id)
    if personality_id is None:
        return None
    return game.table.cards_by_id[personality_id]
```

Every reader is that short, because the relation is the answer. {func}`~.attachments_of` scans it
the other way, and {func}`~.unit_of` is a Personality plus what that scan returns.

`TableState.attachments` is how the table draws the stack. Reading it in a rules function is a bug
even when the answer happens to match.

## Asking who is where

{func}`~.attached_to` gives the Personality, or None. {func}`~.attachments_of` gives what hangs on
one, in attach order. {func}`~.unit_of` is the Personality plus those, and a card with nothing
attached is a unit of one, so a caller never has to check first.

{func}`~.shares_unit` is what most card text about units needs:

```python
def shares_unit(game: GameState, card: L5RCard, other: L5RCard) -> bool:
    """Whether ``card`` and ``other`` stand in the same unit (CR, Unit). A card shares a unit with
    itself, so a text about "cards in this unit" covers the card it is printed on."""
    return other in unit_of(game, attached_to(game, card) or card)
```

A card shares a unit with itself. "Cards in this unit have -1F" includes the card printing it.

One ordering trap, from {func}`~.unit_of`: read the unit before moving the card. Leaving the
battlefield clears the relation, so a handler that moves first then asks finds a unit of one.

## Force and keywords

{func}`~.followers_of` is Followers alone, because the rules ask about them alone. A Follower stands
in the unit with a Force of its own. An Item or a Spell hands the Personality a modifier instead,
which is already inside his effective Force.

That distinction is the whole of the battle-resolution rule in {func}`~.unit_force`:

```python
# An Item's modifier is already inside the Personality's effective Force, so dropping him drops
# what his Items lend him — which is what the rule says happens.
total = 0 if personality.bowed else effective_force(game, personality)
return total + sum(
    effective_force(game, follower) for follower in followers if not follower.bowed
)
```

Outside resolution every card in the unit counts, bowed or not. Inside it a bowed Personality and a
bowed Follower contribute nothing, while a bowed Item still lends its Force, because that Force is
already the Personality's own.

{func}`~.unit_keywords` intersects: the unit has the keywords the Personality and every Follower
share. Items and Spells take no part. Infantry is never a member of the set, being the absence of
Cavalry rather than a keyword, so a unit is Infantry exactly when Cavalry is missing.

## What a card may hang on

{func}`~.may_attach` asks the card's own text first, then the rulebook:

```python
restriction = ATTACH_RESTRICTIONS.get(card.printed_id)
if restriction is not None and not restriction(game, personality, card):
    return False
if is_spell(card) and not may_cast_spells(game, personality):
    return False
if keywords.WEAPON not in effective_keywords(game, card):
    return True
return may_attach_weapon(game, personality, card)
```

The Weapon count and Two-Handed exclusivity are rulebook limits and live in `rulebook/equip.py` as
code. A restriction only one card states is registered with that card, which is what
`@attach_restriction` is for.

A created attachment is judged by {func}`~.may_attach_created` instead. The card does not exist yet,
so its keywords come off the print, and a per-card restriction cannot apply to something with no
text of its own.

## Two things that need no handler

A card leaving play takes its attachments with it. An attachment that comes loose by any other route
is caught by a state-based action:

```python
def orphaned_attachments(game: GameState) -> list[Effect]:
    """Discard every attachment in play that is attached to no Personality (CR, Attachments).

    A Follower, Item or Spell exists in play only as part of a unit, so one left on the battlefield
    without a Personality is not a board state the rules allow. The destruction cascade already takes
    a unit with its Personality; this catches every other route by which a card comes loose.
    """
```

Writing either of these onto a card duplicates a rule that already fires.

## Where a card plugs in

Through `@attach_restriction` for what it will hang on, `@attachment_grant` for a stat it gives its
Personality, and ordinary abilities for everything else.
[Cards that attach](../../contributing/attachments.md) is the worked version.
