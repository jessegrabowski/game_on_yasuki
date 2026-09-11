# Reading card text

This page is a list of traps, not a guide to the templating. Each entry is something that was
modeled wrong, or nearly was, while encoding a real card. It grows when someone finds the next one.

That shape is deliberate. A wrong hook fails loudly and you fix it in an afternoon. A misread card
registers, passes its tests, and is quietly wrong for as long as nobody replays that situation.
The traps below all share one property: the printed text reads as though it says more than it does.

## Which rules a card is read against

There is no single L5R rulebook. The game ran across fourteen arcs, from Clan Wars to the present
one, and they disagree about real things: the pre-Gold rulebook granted four uses of the Imperial
Favor, Gold Edition removed them all, and the current rulebook grants two.

The card data spans all fourteen. The engine models one at a time, and which one is
{class}`~.Ruleset`, a frozen object of arc constants that is swapped wholesale rather than edited
in place. `ACTIVE` names the arc in play. `SHATTERED_EMPIRE` is the current one, and `IMPERIAL` is
written beside it for the pre-Gold rulebook.

**So a card is read against the rules of the arc it is played in, not against the newest ones.** A
card from Imperial Edition in 1995 and its reprint in the current arc can carry the same text and
mean different things.
Reading an old card by today's rulebook is the same class of mistake as every trap below, and the
one most likely to bite when an arc that is not the active one gets implemented.

For the active arc, two published documents settle the text, and the card modules cite both. The
**Comprehensive Rules** for *Legend of the Five Rings: Twenty Festivals* is the full rules text,
cited by section as `(CR, Unit)` or `(CR, Action Sequence)`. The **Shattered Empire datasheet**,
from the Onyx Lives project, amends it, cited as `(ShE datasheet, Winds)`. Where they disagree the
datasheet wins. Every entry below names which settles it.

## A keyword before the timing is not part of the timing

{card}`Touch of Death` reads *"Maho Limited: Bow this Shugenja and destroy this Spell to destroy a
target bowed Personality with equal or lower Chi."*

It looks like `Maho Limited` is a designator of its own. It is a **Limited** ability on a card
carrying the Maho keyword, and the prefix restricts nothing, neither who may use it nor what it may
target. The datasheet gives the rendering rule: a Spell with the Air and Water keywords and an
action reading "Open: Draw a card" prints as "Air Water Open: Draw a card".

`Favor Limited` is the real exception. It is a genuine compound tied to the Imperial Favor, and the
Comprehensive Rules give it its own entry.

## The bow icon bows the card the ability is on

On an attachment it looks like the Personality pays. The Comprehensive Rules: "the bowing icon
means the player needs to bow the card the ability is on". So the attachment bows itself.

Only the written-out form reaches the parent. {card}`Touch of Death` pays with "Bow this Shugenja",
and the rules confirm that phrase names the Personality by adding that it "cannot have the cost
paid by a non-[Shugenja]".

## A comparison with no referent means the source

{card}`Touch of Death` destroys a Personality "with equal or lower Chi". Lower than what is not
printed, and it is tempting to read a fixed number.

It is the caster. {card}`Flame's Hunger` settles it by spelling the same comparison out: "Focus
Value equal to or lower than **their** Chi", where *their* is the Shugenja carrying the Spell.

This one rests on a corroborating card rather than a rules citation, which makes it the weakest
entry here.

## "Search your discard pile, then deck" is an order, not a choice

{card}`Brothers in Arms` searches "your Fate discard pile, then deck". The deck is read only when
the discard holds no copy.

Reading it as a choice matters, because searching the deck costs a shuffle and searching the
discard does not, so a player who could choose would sometimes prefer the worse-looking option.

## A reminder in parentheses is not a rule that card carries

{card}`Carpenter Shrine` prints *"(Fortifications attach to the Province from which they entered
play.)"* Eighty-seven cards carry the Fortification keyword and five print that sentence.

The keyword carries the rule on all eighty-seven. Encoding it per-card would give one Province two
attachments where the rules give it one. The tell is the parentheses, and the same sentence
appearing verbatim on unrelated cards.

## A card that restates a default needs no handler

{card}`Empty Crevasse` reads *"This Fortification enters play bowed. Bow: Produce 3 Gold."* Both
clauses are already the rulebook: every Holding enters play bowed, and Gold Production is a printed
stat rather than behavior. The card needs no handler at all.

The reverse is not free. "Enters play unbowed" overrides the default, and `register_enters_unbowed`
is what carries it.

## Invest changes the stat, a discount does not

The two read alike on the card. "Paying 2 more Gold" leaves the Gold Cost stat alone, while
`Invest :g2:` raises it permanently. Cards that read a Gold Cost see the raised value, so the
difference is visible to other cards rather than only to the purchase.

## Adding to this page

An entry earns its place by naming the card that nearly went wrong and what settles the reading. If
the only support is that it sounds right, it is a judgment call and belongs in a pull request
discussion instead.

## Then pick a hook

[Adding a Card](adding_a_card.md) maps printed wording to hook. [What a card is](what_a_card_is.md)
covers the type vocabulary, and [How card data is authored](the_card_data.md) covers the derived id
every hook keys on.
