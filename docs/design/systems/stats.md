# Stats: printed against effective

A card's Force is two different numbers. There is the one printed on it, and the one it has right
now with an attachment, a Strategy and a Province bonus counted in. Every rule that cares reads the
second.

One prefix marks that second reading everywhere. A function beginning `effective_` means the same
thing wherever it appears: ask the board what this is, do not read the print.

No effective value is ever stored. The CR gives a stat no state beyond its printed number and
whatever is true of the board when someone reads it, so every read derives the value again from
counters, attachments, the cards in play and the records in force, and there is no cache to
invalidate when the board changes. A read costs a few hundred nanoseconds, and that is the budget
every derived source spends within.

## The read path

{func}`~.effective_stat` is the whole calculation:

```{literalinclude} ../../../src/yasuki_core/engine/rules/stats/calculation.py
:start-at: base = getattr(card, stat.value, None)
:end-at: return max(floor, min(cap, total))
:dedent: 4
:language: python
```

Three steps, and the order is the rulebook's. The printed value, plus every active modifier summed,
then floored and capped. A card printed 2F, penalized -3F and then given +2F reads 1 rather than 2,
because the minimum applies to the total rather than to each step.

The one maximum the rulebook imposes is a dishonorable Personality's Personal Honor of 0, and
{func}`~.stat_maximum` is where it lives. A minimum granted above that cap cancels both, so only
the basic floor of zero remains (CR, Minimums and Maximums).

A stat the card type does not have, and a stat printed as a dash, both read zero and take no
modifiers at all.

The named readers wrap it. {func}`~.effective_force`, {func}`~.effective_chi`,
{func}`~.effective_personal_honor` and {func}`~.effective_weapon_limit` each pass one `Stat`.
{func}`~.effective_keywords` answers the same question for keywords, and
{func}`~.effective_province_strength` for a Province.

## Recorded and derived

A change to a stat is one of two kinds, and which kind decides where it lives.

A recorded change comes from an action. It is written into `game.ongoing` as data, a
{class}`~.Duration` ends it, and it outlives whatever created it, so a Strategy in the discard can
still be the source of one. Because replay compares it by value, a record holds only data: a
target id or a {class}`~.Condition`, and a fixed amount.

A derived change comes from a card in play. Nothing is written anywhere, since the card being on
the battlefield is the whole record. It is read off the board on every read and ends the moment
the card leaves. Because nothing stores it, it can be code, and `@stat_grant` is that code.

Each payload has one atom per kind. A stat delta is {class}`~.Modifier` or
{class}`~.ConditionalModifier` when recorded and `@stat_grant` when derived. A keyword is
{class}`~.KeywordGrant` or `@keyword_grant`. An ability is {class}`~.AbilityGrant` and a stat
floor is {class}`~.Minimum`, and neither has a derived form until a card asks for one. A new derived hook
takes `(game, granting, card, ...)` and decides its own scope in its first line, and a new record
takes a target or a condition and a fixed value. A derived handler runs on every read of every
card while its card is in play, so it rejects the cards outside its scope before doing any other
work and keeps nothing between calls.

## The seven kinds of ongoing effect

A recorded change is one of seven things, and which one a card needs is decided by what it rests
on.

{class}`~.Modifier` adjusts one stat on one card. It is the common case and everything else is a
departure from it.

{class}`~.ConditionalModifier` adjusts one stat on every card that meets a {class}`~.Condition` at
the moment the stat is read. It names no target, so "Personalities have -1F while attacking"
reaches a Personality Recruited after it was played and stops reaching one the moment he goes
home, with nothing to withdraw. The condition is evaluated on every read and never stored.
[Adding a condition](#adding-a-condition) below shows the code path.

{class}`~.AbilityGrant` gives one card an activated ability. The ability is code, built by the
granting card's `@granted_ability` factory from the `context` the record carries, which is how
"while a target Personality opposes Kaede, she has 'Battle: Ranged 3'" remembers which
Personality was targeted. {func}`~.abilities_for` reads these beside the card's printed
abilities, so a granted ability answers to legality, once per turn and the activation menu the
way a printed one does.

{class}`~.KeywordGrant` grants a keyword instead of a number. Asking whether a card is a Farm
therefore goes through {func}`~.effective_keywords`, never through its printed keywords.

{class}`~.Minimum` floors a stat instead of adding to it, and applies to the total rather than to
any one part of it. Where several apply to one stat, the most restrictive wins.

{class}`~.ProvinceModifier` targets a Province. A Province is a slot on the board and not a card,
so a `Modifier` cannot name one at all.

{class}`~.LobbyModifier` rests on a player. A Lobby Bonus is not a property of any card, and the
datasheet adds that an adjustment to Family Honor through one is neither an Honor gain nor an
Honor loss.

## Adding a condition

A `ConditionalModifier` is read in the same loop as a `Modifier`. The difference is what decides
whether the record reaches the card being read: a `Modifier` compares its `target_id`, and a
`ConditionalModifier` asks {func}`~.condition_holds`:

```{literalinclude} ../../../src/yasuki_core/engine/rules/stats/calculation.py
:start-at: for recorded in game.ongoing:
:end-at: yield Modifier(recorded.source_id, card.id, stat, recorded.amount, recorded.duration)
:dedent: 4
:language: python
```

Each `Condition` is one predicate over the game and a card, in
`src/yasuki_core/engine/rules/stats/conditions.py`. `ATTACKING` is the first:

```{literalinclude} ../../../src/yasuki_core/engine/rules/stats/conditions.py
:pyobject: _attacking
:language: python
```

A new condition is an enum member on {class}`~.Condition` with a line of docstring saying what it
asks, a predicate like this one, and an entry in the module's table mapping the member to it. The
predicate reads the board and nothing else. It is called on every stat read of every card while a
record naming it is in force, so it does no work it can avoid and stores nothing between calls. The
docstring names the exact scope, since {card}`Flashy Technique` says "Personalities" and
`ATTACKING` is therefore a Personality in the attacking army, while a card saying "units" would
want a member of its own.

The rest of the machinery reads the record as it reads any other. `grant_applies` looks at its
`duration` and `source_id`, the end-of-turn sweep drops it by `duration`, and the sweep that
forgets records whose target left the table keeps it, since it has none.

## How long one lasts

`Duration` has three values. `UNTIL_END_OF_TURN` is the default for an action or an ability.
`WHILE_SOURCE_IN_PLAY` expires when the card the effect came from leaves the battlefield, which is
how counters, attachments and continuous auras are held. `PERMANENT` outlives its source and still
ends when its *target* leaves the table, because a card that leaves play ceases to exist.

## Where a card plugs in

A card in play whose text gives a stat to a card, itself or another, uses `@stat_grant`, and its
handler names the scope, as {card}`Haramaki-do` reaching the Personality it hangs on. A card that
grants a keyword sometimes uses
`@keyword_grant`. A card that changes a Province's strength uses
`@province_strength_grant`.

For which hook a printed sentence wants, see [Adding a Card](../../contributing/adding_a_card.md).
For the decision of whether a number needs a handler at all, see
[Printed and computed values](../../contributing/stats_and_costs.md).
