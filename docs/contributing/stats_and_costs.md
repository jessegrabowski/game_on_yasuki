# Printed and computed values

Every number on a card is one of two things. It is printed, and the engine reads it off the card.
Or it is computed, and a handler answers for it. A first card goes wrong in both directions: a
handler written for a number the engine already reads, and a number left to the engine that it
never sees.

## One card, both kinds

{card}`Haramaki-do` is an Item that prints **+2F** as a stat and reads *"This Personality has
+1PH. Battle: Fear 3."*

The +2F needs nothing. It is a printed stat on the attachment, and the engine adds it when it
totals the Personality's Force.

The +1PH is written in the text, so it is a grant:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/ivory_edition.py
:pyobject: _haramaki_do_attachment_grant
:language: python
```

Two bonuses on one card, and only one is code. The docstring says which is which. Copy that habit.

## The test

Ask where the number lives. A value in a stat field on the card is data, and the engine already
reads it. A value stated in the card's text is behavior, and behavior needs a hook.

That is why "This Fortification enters play bowed" needs no handler while "enters play unbowed"
does. The first restates what the rulebook already does, and the second overrides it.

## Reading a stat, never a print

A handler that needs a card's Force asks {func}`~.effective_force`, never `card.force`. The printed
value is the starting point of a calculation that attachments, Strategies and Province bonuses all
contribute to, and a handler reading the print sees none of them.

The same holds for keywords. {func}`~.effective_keywords` is how you ask whether a card is a Farm,
because a card can be granted the keyword by something else in play. The `effective_` prefix marks
every function in the family.

## Where the rest lives

[Stats: printed against effective](../design/systems/stats.md) covers the read path and the five
kinds of ongoing effect. [Holdings and gold](holdings_and_gold.md) covers the same split on the
production side.
