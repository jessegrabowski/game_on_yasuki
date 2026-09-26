# Build from the vocabulary

The engine grows by composition. A card, a rulebook procedure or a turn step is written as a
combination of the effects, decisions, events, moments and registries that already exist, and a new
one of those is added only when no combination of the existing ones can say what the rules say.
This is the first design question for any engine change, ahead of where the code goes or what it is
called.

## Why the vocabulary stays small

Every noun in [the card vocabulary](card_vocabulary.md) has a fixed cost that grows with the engine.
An effect carries its own `perform`, `describe`, `is_payable` and `is_interruptible`, and each has
to be right for every place the effect can appear. A decision has to be answerable by every seat
type, which includes the bots, the desktop client and the replay tape. Every trigger in the engine
can subscribe to an event, and a registry is a hook that
[registration and the audit](systems/registration-and-the-audit.md) has to check and
[bots and policies](systems/bots-and-policies.md) has to score. A term with one user pays all of
that for one card.

Two terms that say the same thing cost more than twice as much. They drift, a fix lands in one and
not the other, and an interaction written against one silently misses cards written against the
other. A card that reacts to discards has to see every discard, which it cannot do if three cards
each discard through their own path.

The replay log is complete only if every change is a term the log knows, and a learned policy
generalizes across cards only if the cards are made of shared parts. Both depend on the vocabulary
staying small.

## Decompose before adding

Read the text, the card's or the CR's, as a sequence of rule-level verbs: bow, discard, choose,
gain, move, delay until a boundary of play. Each verb is a candidate for an existing term. For each
one:

1. Find the term that already does it. [The card vocabulary](card_vocabulary.md) lists every effect,
   event, decision and ongoing type, and [Adding a card](../contributing/adding_a_card.md) lists
   every registry.
2. Where a term almost fits, the question is whether the difference is in the rules or only in the
   wording. A choice among cards is `Choose` whether the cards are in a hand, a deck or a province.
   An effect that waits for a boundary of play is `DelayedEffect` whether the boundary is the end of
   a battle or the end of a duel.
3. Where nothing fits, look for the smallest missing piece. That is usually a parameter on an
   existing term, a new `Moment`, or a new board query, and rarely a new effect, decision or
   registry.

A new term is right when the CR names a primitive the vocabulary lacks and a second card could use
it unchanged. Name it for the rule's verb. A term named for a card, a keyword or a mechanic
(`BanishForLegacy`, `register_edict`, a resolver keyed `"<card>_discard"`) is a composition wearing
a primitive's name, and the second card that wants the same verb will not find it there.

## What adding one owes

A new term replaces every bespoke path that already did its job, in the same change. Leaving the old
paths in place leaves two ways of saying one thing. When `register_entry` arrived, `register_edict`
was migrated onto it and deleted in the same pull request.

Removal goes with it. A hook with one caller, a field nothing reads, and a function that only
forwards its arguments are each a term with no job, and deleting them is part of the work.

## Worked examples

Legacy's search once asked three questions of its own: `BanishForLegacy`, `ChooseLegacyCard` and
`PlaceLegacy`, each a `DecisionRequest` subclass with its own prompt and validation. Each is a
choice of cards. They became `Choose` effects with resolvers, and the three classes were deleted
from the decisions module.

Edicts put themselves into play from hand through `register_edict`. A Kata and an action-entry Ring
print the same shape: an ability taken from hand whose effect is the card entering play. That shape
is `register_entry`, keyed on what the card does and not on its type, so the three card types share
one path.

A duel's consequences ("apply these consequences now") were once held by the duel itself. The CR's
wording is a delayed effect, the same thing "after this battle ends" is. They became
`DelayedEffect` to a new `Moment`, `DUEL_CONSEQUENCES`, which the flow fires as the duel ends. The
missing piece was one moment, and the duel has no consequence machinery of its own.

The duel's focus procedure had a setup hook that its only implementation answered with an empty
list, and `focus_sources` did nothing but forward to the procedure. Both were deleted.

## In review

These are the signs a change added where it could have composed:

- A new effect, decision, event, work item or registry whose name contains a card title, keyword
  or mechanic.
- A new term with exactly one caller.
- A new term that does what an existing one does, with a different trigger point or a different
  prompt.
- A handler that builds by hand what an existing effect or query already does.
- A diff that adds a general term and leaves the specific ones it generalizes.

The registries in [Adding a card](../contributing/adding_a_card.md) include some with one user. They
predate this page, and each is a candidate for folding into a more general term. None is a precedent
for adding another.
