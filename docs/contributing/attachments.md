# Cards that attach

A Follower, Item or Spell is written the same way as anything else. What sets one apart is that it
acts through the Personality carrying it, and that the rules already handle most of what that
implies. [Units and attachments](../design/systems/units-and-attachments.md) is the system behind
this page.

## The two bow costs are different

The `:bow:` icon in a cost line bows **the card the ability is on**, which for an attachment is the
attachment. Only the written-out "Bow this Shugenja" reaches the Personality. Read the printed
line before choosing a cost, because the icon and the sentence look equally like "bow something"
and are not the same cost.

{func}`~.bow_cost` is the icon. {func}`~.bow_parent_cost` is the written-out form:

```python
def bow_parent_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Personality ``source`` is attached to. Unpayable while it is attached to none."""
    parent = attached_to(game, source)
    if parent is None:
        return [Unpayable(f"{source.id} is attached to no Personality")]
    return [Bow(parent.id)]
```

{card}`Touch of Death` pays with {func}`~.bow_parent_and_destroy`, which bows the Personality and
destroys the Spell.

## Giving the Personality a stat

```{card-image} Haramaki-do
:printing: ivory_edition
:width: 220px
```

`@attachment_grant` is for a stat the attachment's text hands over. {card}`Haramaki-do` prints +2F
and reads "This Personality has +1PH", and only the second half is a handler:

```python
@attachment_grant("haramaki_do")
def _haramaki_do_attachment_grant(game: GameState, card: L5RCard, host: L5RCard) -> dict[Stat, int]:
    """This Personality has +1PH. The +2F is printed on the card and needs no handler."""
    return {Stat.PERSONAL_HONOR: 1}
```

A printed number on an attachment already reaches the unit through {func}`~.unit_force`.
[Stats and costs](stats_and_costs.md) is when a number needs a handler at all.

## Limiting what it will hang on

The rulebook's own limits, one Weapon and Two-Handed exclusivity, are already code. A restriction
that only one card states is registered with that card:

```python
@attach_restriction("brothers_in_arms")
def _brothers_in_arms_attach_restriction(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    return keywords.SAMURAI in effective_keywords(game, personality)
```

## Ancestors

An Ancestor is a Fate type of its own that attaches to a Personality, so it belongs on this page
rather than with the cards that play from hand and stay in play. Nothing is implemented for one
yet: {class}`~.AttachmentType` has `ITEM`, `FOLLOWER` and `SPELL`, and an Ancestor is none of the
three, so the first Ancestor written needs that decided first.

## Two things to leave alone

A card leaving play takes its attachments with it, and an attachment left with no Personality is
discarded by a state-based action. Both fire without a handler, and writing either onto a card
duplicates a rule that is already running.

## Where the rest lives

[Cards that act in a battle](battle_cards.md) covers an attachment with a Battle ability, which is
most of the printed corpus. [Writing an ability](an_ability.md) is the starting point for any of
them.
