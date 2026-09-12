# Board queries

`rules/board/queries.py` is the vocabulary for asking the board a question. Every function there
takes the game and answers in cards or ids. A handler that reaches into `game.table` and filters
by hand is nearly always rewriting one of them.

## Provinces

{func}`~.province_zones` yields each of a seat's Province zones with its key, in table order, and
{func}`~.province_cards` yields the cards in them.

Two functions find the Province holding a card, and the difference is what they do when none does:

```{literalinclude} ../../../src/yasuki_core/engine/rules/board/queries.py
:pyobject: province_key_of
:language: python
```

{func}`~.province_key_holding` returns None. {func}`~.province_key_of` raises. Reach for the second
when the card being there is already established, so a bug surfaces where it happens rather than as
a None carried somewhere else.

{func}`~.province_holdings` gives the ids of the Holdings in a seat's Provinces.

## Cards in play

{func}`~.personalities_in_play` is every Personality on the board. {func}`~.owned_personalities`
narrows that to one seat. {func}`~.owned_holdings` does the same for Holdings and takes an optional
keyword to filter on.

{func}`~.has_keyword` answers whether a card carries a keyword, printed or granted, matched without
regard to case. It reads through {func}`~.effective_keywords`, so a keyword another card granted
counts. Comparing against `card.printed.keywords` misses those.

## Battle

{func}`~.units_at` is the units a seat has at one battlefield.
{func}`~.opposing_units_in_battle` is the enemy's in the battle being fought.
{func}`~.attack_targets` is the predicate every attack card wants, and
[Battle](battle.md) covers what it answers to.

## The other two modules

`board/` holds three modules and `queries.py` is only the largest. The other two answer questions
about a seat rather than about the board.

{func}`~.is_clan` in `board/clans.py` is the one a card condition reaches for most, and
{func}`~.seat_alignments` and {func}`~.card_alignments` are what it reads. Clan alignment is not a
single string, which is why these exist rather than a field comparison.

`board/seats.py` has {func}`~.cards_in_play`, {func}`~.seat_stronghold`,
{func}`~.seat_controls_printed`, {func}`~.cards_named`, {func}`~.opposing_seats` and
{func}`~.went_second`. A card asking whether its controller has something in play wants one of
these.

## Where a card plugs in

By calling these instead of walking `game.table`. A question this module cannot answer belongs
here, because the next card that asks it will otherwise write its own version.
