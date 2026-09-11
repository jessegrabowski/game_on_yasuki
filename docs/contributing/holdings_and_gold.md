# Holdings and gold

A Holding's whole job is to make gold when it bows. Most need no code at all, because the amount is
printed on the card and the engine reads it. A handler is for the ones where the amount depends on
something.

## When the amount is printed, write nothing

A Holding with a `gold_production` of 2 produces 2. There is no hook to register and no function to
write. Reach for one only when the printed number is wrong for some situation the card describes.

## When it depends on what is being bought

{card}`Jade Works` reads *"Bow: Produce 3 Gold. Bow: Produce 5 Gold, which can only pay for a
single Jade card."* The amount depends on the purchase, so the handler is handed the cards being
paid for:

```python
@gold_handler("jade_works")
def _jade_works_gold(
    card: L5RCard, game: GameState, seat: PlayerId, targets: tuple[L5RCard, ...]
) -> int:
    """+2 GP when paying for a Jade card."""
    bonus = 2 if any(keywords.JADE in target.keywords for target in targets) else 0
    return card.gold_production + bonus
```

`targets` is what the seat is buying. The handler adds to the printed value rather than replacing
it, which keeps a Wealth token on the card counting.

## When it depends on the board

{card}`Teardrop Island` produces on a clan condition, and {card}`Colonial Farm` shows the same
shape on the cost side rather than the production side:

```python
@recruit_discount("colonial_farm")
def _colonial_farm_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if is_clan(game, seat, ruleset.LION) else 0
```

That is the whole card. The condition is the implementation, and the shared predicates for clan and
keyword questions live in the `board/` package. Look there before writing one.

## When the card acts while it produces

{card}`Jade Mine` reads *"When this Holding produces Gold, you may give it +1GP this turn; if you
do, it will not straighten."* That is a question asked at the moment of bowing.

Declare the amount with `register_self_grant`, so affordability can count gold the seat has not yet
been offered. A seat deciding whether it can afford something needs to know the grant exists before
anyone asks about it.

## Where the rest lives

[The gold economy](../design/systems/gold.md) covers producing, affordability and payment. For
which hook a printed sentence wants, see [Adding a Card](adding_a_card.md).
