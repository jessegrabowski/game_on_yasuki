# Stats: printed against effective

A card's Force is two different numbers. There is the one printed on it, and the one it has right
now with an attachment, a Strategy and a Province bonus counted in. Every rule that cares reads the
second.

One prefix marks that second reading everywhere. A function beginning `effective_` means the same
thing wherever it appears: ask the board what this is, do not read the print.

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

## The six kinds of ongoing effect

A modifier is one of six things, and which one a card needs is decided by what it rests on.

{class}`~.Modifier` adjusts one stat on one card. It is the common case and everything else is a
departure from it.

{class}`~.ConditionalModifier` adjusts one stat on every card that meets a {class}`~.Condition` at
the moment the stat is read. It names no target, so "Personalities have -1F while attacking"
reaches a Personality Recruited after it was played and stops reaching one the moment he goes
home, with nothing to withdraw. The condition is evaluated on every read and never stored.

{class}`~.KeywordGrant` grants a keyword instead of a number. Asking whether a card is a Farm
therefore goes through {func}`~.effective_keywords`, never through its printed keywords.

{class}`~.Minimum` floors a stat instead of adding to it, and applies to the total rather than to
any one part of it. Where several apply to one stat, the most restrictive wins.

{class}`~.ProvinceModifier` targets a Province. A Province is a slot on the board and not a card,
so a `Modifier` cannot name one at all.

{class}`~.LobbyModifier` rests on a player. A Lobby Bonus is not a property of any card, and the
datasheet adds that an adjustment to Family Honor through one is neither an Honor gain nor an
Honor loss.

## How long one lasts

`Duration` has three values. `UNTIL_END_OF_TURN` is the default for an action or an ability.
`WHILE_SOURCE_IN_PLAY` expires when the card the effect came from leaves the battlefield, which is
how counters, attachments and continuous auras are held. `PERMANENT` outlives its source and still
ends when its *target* leaves the table, because a card that leaves play ceases to exist.

## Where a card plugs in

A card that grants a stat to the Personality it hangs on uses `@attachment_grant`. A card that
grants a keyword sometimes uses `@keyword_grant`. A card that changes a Province's strength uses
`@province_strength_grant`.

For which hook a printed sentence wants, see [Adding a Card](../../contributing/adding_a_card.md).
For the decision of whether a number needs a handler at all, see
[Printed and computed values](../../contributing/stats_and_costs.md).
