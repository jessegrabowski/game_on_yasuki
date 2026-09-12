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

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/pre_imperial.py
:pyobject: _jade_works_gold
:language: python
```

`targets` is what the seat is buying. The handler adds to the printed value rather than replacing
it, which keeps a Wealth token on the card counting.

## When it depends on the board

{card}`Teardrop Island` produces on a clan condition, and {card}`Colonial Farm` shows the same
shape on the cost side rather than the production side:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/promotional_emperor.py
:pyobject: _colonial_farm_recruit_discount
:language: python
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
