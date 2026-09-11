# The gold economy

Gold is made and spent inside one phase. A seat bows Holdings to produce it, spends it on cards,
and loses whatever is left when the phase ends. Nothing carries over, which is why affordability
has to be answered before a seat commits to anything.

## Producing

{func}`~.effective_gold_production` answers what one card makes right now. It is the printed
`gold_production`, or a registered handler's result where the card has one, plus every active Gold
Production modifier, floored at zero. A card with no Gold Production stat produces nothing and
takes no modifiers.

`@gold_handler` registers one, and it is the right hook whenever the amount is not fixed.
{card}`Jade Works` produces a different amount depending on what is being bought.
{card}`Teardrop Island` produces 2, or 3 for a Mantis Clan player.

Counters reach production without a handler. A Wealth token declares the stat it grants, so
{card}`Rice Farm`'s four tokens raise its production through the modifier path rather than through
code.

## The production window

A card can act *while* it produces. {card}`Jade Mine` reads "When this Holding produces Gold, you
may give it +1GP this turn; if you do, it will not straighten". The question comes at the moment of
bowing, not before or after it.

`register_self_grant` declares the amount such a card can add, and `GOLD_SELF_GRANT` is the list of
cards that can. Declaring it separately is what lets affordability count gold the seat has not been
offered yet. {func}`~.is_production_window` recognizes the question by the card asking it.

## Affordability

{func}`~.reachable_gold` totals what a seat could raise, which is not the same as what it has in
the pool. It walks the unbowed producers, counts what each would make, and includes the self-grants
nobody has been asked about yet.

That total decides whether a purchase is offered. Two things go wrong at that boundary. A purchase
the seat cannot complete should never be offered, and one it could reach by taking a grant should
never be withheld.

{func}`~.refusal_would_strand` guards the first. A seat that declines a grant must not be left with
a payment it has already committed to and can no longer make.

## Spending

{func}`~.effective_gold_cost` is the other half of the printed-against-effective split.
{func}`~.effective_recruit_discount` and {func}`~.effective_invest_discount` are the registries a
card plugs a conditional discount into, and a discount reduces what is paid without changing the
Gold Cost stat any other card reads.

{func}`~.payment_request` builds the question a seat answers to pay, and {func}`~.can_afford`
decides whether it may be asked at all.

## Where a card plugs in

`@gold_handler` for a variable amount, `@recruit_discount` and `@invest_discount` for conditional
discounts, `register_self_grant` or `@self_grant` for a card that raises its own production as it
bows.

For a worked example of each, see
[Holdings and gold](../../contributing/holdings_and_gold.md).
