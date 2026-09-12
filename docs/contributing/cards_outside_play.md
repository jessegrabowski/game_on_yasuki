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

```python
game.stack.append(DiscardPlayed(card_id))
defer_ability(game, card, ability)
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

```python
def discard_played(game: GameState, card_id: str) -> None:
    """Discard a card whose play has finished, unless it has already left the hand.

    Step F discards the played card "unless it is now in play" (CR, Action Sequence) — a Terrain, a
    Kata or an Edict reaches the board as the thing its own text does. A card that banished itself has
    left by another road, and discarding it would drag it back out of the pile it chose, so the
    test is whether it is still in hand rather than whether it reached the board.
    """
    card = game.table.cards_by_id[card_id]
    if card not in game.table.zones[ZoneKey(card.owner, ZoneRole.HAND)].cards:
        return
    triggers.resolve_effects(game, [Discard(card_id, card.owner)])
```

So the handler says one thing and the discard takes care of itself:

```python
return [PutIntoPlay(source.id)]
```

Two kinds that look like they belong here do not. An **Ancestor** is a Fate type that attaches to a
Personality, so it is an attachment and [Cards that attach](attachments.md) covers it. A **Tattoo**
is a Strategy that grants a lasting ability and is then discarded like any other Strategy, so
nothing about it stays.

## Edicts and Kata, which clear their own kind

An Edict puts itself into play and discards your others, which is the rulebook's limit of one at a
time restated on the card:

```python
def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    others = [
        card.id
        for card in game.table.battlefield.cards
        if card.owner is source.owner
        and card.id != source.id
        and keywords.EDICT in effective_keywords(game, card)
    ]
    return [
        PutIntoPlay(source.id),
        *(Discard(card_id, source.owner) for card_id in others),
    ]
```

{func}`~.register_edict` bundles that with an `Open` ability and
`located_at=(CardLocation.HAND,)`, so registering one takes a line:

```python
register_edict("act_with_authority")
register_edict("way_of_the_crab_experienced", clan=ruleset.CRAB)
```

The optional `clan` is for the Edicts naming a clan their controller must be playing.

**Kata print the same shape**, "put this card into play, discard all your other Kata."
`register_edict` hardcodes `keywords.EDICT`, so a Kata cannot use it as it stands. The same
function taking the keyword as an argument would cover both, and that is the shape to reach for
when the first Kata is written.

## Terrain, which attaches to a battlefield

Terrain is by far the largest of these kinds and does not follow the pattern. A Terrain enters play
attached to a battlefield, not to a seat, so what it has to get along with is whatever Terrain is
already there. How that is handled is the card's own business and varies across the pool. Many
print an explicit "Destroy a Terrain" clause ahead of putting themselves into play, and many say
nothing of the kind. Nothing is implemented for Terrain yet, and the first one written has to
settle what a battlefield attachment is before it can settle anything else.

## Where the rest lives

[Abilities and costs](../design/systems/abilities-and-costs.md) covers `located_at` alongside the
other optional fields, and [Action lifecycles](../design/systems/action-lifecycles.md) covers what
happens between announcing and resolving.
