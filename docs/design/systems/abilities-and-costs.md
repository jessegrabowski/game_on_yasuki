# Abilities and costs

An activated ability is the most-used hook in the card module. It is also the one that breaks the
rule the others follow.

Every other hook is a decorator on a function. This one is a plain call, and its second argument is
a dataclass carrying five callables. {card}`Poorly Placed Garden` is the plainest complete one:

```python
register_ability(
    "poorly_placed_garden",
    Ability(
        timings=(ActionTiming.LIMITED,),
        label="Limited: bow this Holding to gain 2 Honor",
        cost=bow_cost,
        targets=_poorly_placed_garden_targets,
        effects=_poorly_placed_garden_effects,
        hits_every_target=True,
    ),
)
```

The shape is deliberate. An ability is four things that have to travel together, and a decorator on
any one of them would leave the other three somewhere else on the page.

## The four parts

**Timing** says when the ability may be taken, and by whom. `timings` is a tuple because a
Shattered Empire card can print two designators, and an ability carrying several may be used in any
round that permits any of them.

**Cost** is what the seat pays to announce it. It maps the game and the source card to the effects
that paying produces, so a cost is itself a list of effects rather than a number.

**Targets** maps the game and the source to the ids the ability may be pointed at. Returning an
empty list means the ability cannot be offered at all, which is how a card with no legal target
stays off the menu.

**Effects** maps the game, the source and one chosen target to what the ability does.

`hits_every_target=True` changes the last two. The ability resolves against every id `targets`
returns instead of asking the seat to pick one, which is how an untargeted "your other Farms" grant
is written. Poorly Placed Garden above uses it to act on itself.

## Where a cost builder lives

`abilities/costs.py` holds the builders more than one card uses: {func}`~.no_cost`,
{func}`~.bow_cost` and {func}`~.bow_parent_cost`. {func}`~.can_pay` sits beside them and answers
whether a given cost is payable now.

A cost only one card charges lives with that card, as `_<card id>_cost`, the way a target predicate
or an effects function does. That is the same rule `@attach_restriction` and the other per-card
registries follow, and it means a new combination of effects needs no new shared name.

`bow_cost` and `bow_parent_cost` are the pair to be careful with. `bow_cost` bows the card the
ability is on. `bow_parent_cost` bows the Personality an attachment is attached to, and is
unpayable while it is attached to none. The printed card does not make the difference obvious, and
[Reading card text](../../contributing/reading_card_text.md) covers how to tell which one a card
means.

`bow_cost` offers any waiver the card carries before bowing it, so an attachment that waives its
Personality's bow is consulted at the moment of payment.

## The optional fields

`key` names an ability among several its card prints, so an action can say which one it takes.
`tireless` lets an ability be used while its card is bowed. `located_at` says where the card must
be, defaulting to the battlefield. `battle_designators` and `targets_any_location` govern what a
battle ability can reach, and [Adding a Card](../../contributing/adding_a_card.md) explains both
under attachments. `keywords` holds the ability keywords printed ahead of the designator, as in
"Political Battle:", so a card asking whether the resolving action was Political has something to
read. `repeatable` is the Repeatable modifier: an ability on a card in play is once per turn
without it, which `legality.activatable` enforces through the same once-per-turn keys a handler
claims by hand. The registration audit compares both with the card's text and rejects a
registration that leaves one off or invents one.

## What narrows a target list

A handler's `targets` output is not final. `legal_targets` in `legality.py` narrows it by the Rules
of Location before the ability is offered, so a card's own predicate answers what the card says and
the central rule answers where the card may reach.

Write the predicate for the card's text and let the rule do the rest. A handler that tries to
reimplement the Rules of Location will drift from them.

## An Interrupt

A Strategy printing an Interrupt is not an `Ability`. It has no target and no effects of its own,
since what it does is decided against the effect it interrupts, and no round offers it. It is
registered with `register_interrupt` as an {class}`~.Interrupt`, whose `answers` names the effect
type it may be played against and whose `interrupt` maps the pending effect to an
{class}`~.Interruption`: the effect that resolves in its place and whatever else happens. The
Interrupt step in `rules/interrupts.py` offers it from hand while such an effect waits to resolve,
and the Strategy is then paid for and discarded the way any Strategy is. Any effect of the action
can be answered: the step is open against every effect the cascade applies inside one, and an
Interrupt names the type it answers.
