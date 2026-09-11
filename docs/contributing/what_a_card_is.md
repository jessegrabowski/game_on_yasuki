# What a card is

Three different things are called "a card" in this codebase, and a handler touches all three.

A **card record** is a row of YAML: a title, a type, printed stats, rules text. It is data, shared
by everyone.

A **print** is what the engine makes of that record. It is a frozen object of one of twelve
classes, and it is where a card's characteristics live.

A **card** is one physical copy in one game, {class}`~.L5RCard`. It has an identity, a place on the
table, and state that changes: bowed, face up, counters. It points at a print rather than copying
it, so every copy of Rice Farm on the table shares one `HoldingPrint`.

## Identity is split, and handlers key on the shared half

```python
    id: str
    printed: CardPrint
    owner: PlayerId
```

`id` is this copy. `printed_id` is the database id every copy and every printing shares, and that
is what a registry keys on. A trigger registered for `"rice_farm"` fires for all three copies in
play, which is why a trigger about *this* card has to compare `ctx.event.card_id` against
`ctx.card.id`.

Characteristics read forward through the print, so `card.gold_production` answers from
`HoldingPrint`. `isinstance` does not: ask `isinstance(card.printed, HoldingPrint)` for a card's
type.

## The engine's type vocabulary is coarser than the data's

The card data uses eighteen types. Fourteen of them resolve to a print, across twelve classes, so
the mapping is not one to one.

Follower, Item and Spell all resolve to {class}`~.AttachmentPrint`, told apart by an
`attachment_type` field. That is 2,441 distinct cards on one class. If you are looking for a
Follower hook, there isn't one, and a handler that needs to know asks the field.

There is no Province print, because a Province is not a card. It is a slot on the board, and its
strength comes from `province_strength` on the Stronghold. A card that strengthens one records a
`ProvinceModifier` rather than modifying a card.

Four data types resolve to nothing at all: Proxy, Other, Clock and Territory. Proxy entries are the
token templates a card creates, reached by id from a `CreateToken` effect rather than played from
a deck.

## Most cards are not implemented

128 distinct cards have a registered handler, as of 2026-09-11. Ten of the eighteen types have no
handler on any card: Ancestor, Celestial, Clock, Other, Proxy, Region, Ring, Stronghold, Territory
and Wind.

That list is the useful half. Picking a Ring and looking for the hook that would carry it is time
spent on something the engine cannot express yet, and
[what the vocabulary cannot express](adding_a_card.md#what-the-vocabulary-cannot-express-yet) says
which of those are core extensions rather than missing handlers.

## Where a card's behavior goes

See [Adding a Card](adding_a_card.md) for the hook table, and
[Reacting to events](reacting_to_events.md) for a worked trigger.
