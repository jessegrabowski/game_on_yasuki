# Looking at cards

"Look at the top four cards of your Fate deck. Put one in your hand and put the other three on the
bottom of your deck in any order." The cards never leave the deck while the seat reads them, the
questions that follow are several and of different kinds, and once the seat has read the cards
nothing about the action can be taken back. This page is how the engine holds all three.

## The look is state

{class}`~.LookAtTop` moves nothing. It writes a {class}`~.Look` to `GameState.look` naming the
seat, the deck and the cards top first, and marks the seat as a peeker of each:

```{literalinclude} ../../../src/yasuki_core/engine/rules/effects.py
:pyobject: LookAtTop.perform
:language: python
```

The look is a field of the state rather than of any one decision because the chain that follows it
is made of ordinary decisions. "Put one in your hand" is a {class}`~.ChooseCards`, "put the rest
back in any order" is an {class}`~.ArrangeCards`, and {card}`Temples of Gisei Toshi`, which
names a type before looking, asks a {class}`~.ChooseOption` first. Every one of them has to know
which cards are in view, and a client has to know what to draw in the window it opens, so the fact
lives in one place.
{class}`~.EndLook` clears it when the last question is answered.

A handler builds its first question from {func}`~.top_of_deck`, so the candidates and the look
name the same cards. A resolver asking the next question reads {func}`~.remaining_look`, which is
the look filtered to the cards still in the deck, so a card an earlier answer moved to hand has
already left the pool:

```{literalinclude} ../../../src/yasuki_core/engine/rules/cards/a_line_in_the_sand.py
:pyobject: _resolve_beset_from_all_sides
:language: python
```

## Nothing is backed out of

{meth}`EngineSession.cancel <yasuki_core.engine.session.EngineSession.cancel>` refuses while a look
is open, whatever the pending request's own `cancellable` says, and
{meth}`EngineSession.abort <yasuki_core.engine.session.EngineSession.abort>` returns False.
{meth}`EngineSession.can_cancel <yasuki_core.engine.session.EngineSession.can_cancel>` is the one
question a client asks before offering Cancel, so the button is never shown and then refused. A seat
that has read the top of its deck holds information it cannot give back, so the Cancel that was
offered at the cost and at the target is gone from the moment the look opens. This is the same
ruling the rulebook Legacy search has always had, applied to every card of the class at once.

## An order

{class}`~.ArrangeCards` is the one decision the class needed that nothing else asked. Its answer
names every candidate exactly once, in the order the seat placed them:

```{literalinclude} ../../../src/yasuki_core/engine/rules/vocabulary/decisions.py
:pyobject: ArrangeCards.accepts
:language: python
```

The first named is placed first and each later one goes outside it. For a top placement the last
named ends on top, and for a bottom placement the last named ends at the very bottom. That is the
order a client sends when the seat clicks cards one at a time onto the deck, so the client appends
and the engine never reverses. {class}`~.PlaceOnDeck` applies the answer with the same contract:

```{literalinclude} ../../../src/yasuki_core/engine/rules/effects.py
:pyobject: PlaceOnDeck.perform
:language: python
```

`ArrangeCards.to_bottom` says which end, and {attr}`~.ArrangeCards.unchanged` is the answer that
leaves the cards as they were looked at, which a client offers as one click for the seat that does
not care.

## The three endings

Most cards of the class end one of three ways, so the rulebook registers each resolver once and a
card names one instead of writing its own:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/looks.py
:start-at: PUT_BACK_ON_TOP = "put_back_on_top"
:end-at: TAKE_ONE_AND_SHUFFLE = "take_one_and_shuffle"
:language: python
```

The first two put the cards where the seat ordered them, and the third takes one into hand and
shuffles. Each closes the look. A card whose ending is none of these, such as
{card}`Temples of Gisei Toshi` leaving the rest where they lie, closes the look from its own
resolver. A look left open past the end of
its action raises, and a second look opened over the first raises, so a resolver that forgets
{class}`~.EndLook` fails in the test that drives the card rather than by refusing every later
cancel in a game.

## Where the rest lives

The vocabulary is listed on the [card vocabulary](../card_vocabulary.md) page, the decision
lifecycle is [decisions and resumption](decisions-and-resumption.md), and
[asking the player a question](../../contributing/asking_a_question.md) shows a card author the
shapes.
