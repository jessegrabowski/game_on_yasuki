# Cards that act in a duel

```{card-image} Sanctioned Duel
:printing: emperor_edition
:width: 220px
```

A duel is a procedure a card starts. Four shapes of printed text reach it, each hooking in at a
point of its own: the text that creates the duel, an `As a Focus Effect` trait, a consequence for
the winner or the loser, and a reaction at one of the duel's own time points.
[Duels](../design/systems/duels.md) is the system page behind all four.

## Creating the duel

{class}`~.StartDuel` names the two Personalities and nothing else. No duel happens where one player
controls both or either card has left play. The CR's wording is that such a challenge does not
happen at all, so nothing is created and nothing fails.

{card}`Sanctioned Duel` is the worked example, and its first step is the refusal:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/emperor_edition.py
:pyobject: _resolve_sanctioned_duel_refusal
:language: python
```

A card that says "he may refuse" puts the choice to the challenged seat with an
{class}`~.AskOption` *before* `StartDuel`, because a refused challenge creates no duel at all. The
refusal branch's effects are ordinary effects on that branch, not consequences delayed to a duel
that never existed.

A duel needs two targets from two pools, and an ability takes only one. The challenger is the
ability's target and the challenged Personality is a {class}`~.Choose` of its own, which carries the
Strategy's id in `resolver_context` so the second step knows which card is asking.

"A duel of Force" is not a property of the duel. The CR names the duel stat per Personality, so a
card that changes it tells each duelist separately:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/onyx_edition.py
:pyobject: _hida_haikeru_effects
:language: python
```

## As a Focus Effect

`@focus_effect(id)` registers what a card does once a strike has revealed it. The handler takes the
game and the card, and returns effects like any other.

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/the_heavens_will.py
:pyobject: _discretionary_valor_focus_effect
:language: python
```

Three things about the timing are easy to get wrong. The effect resolves at the reveal, not when the
card is focused, so a card raising a Focus Value still counts toward the totals. The active player
orders them when more than one is revealed. And a Focus Effect outlives a duel that another Focus
Effect ended, which is why the handler above reads `game.duel` rather than
{attr}`~.GameState.duel_being_fought`.

A card reached only by being focused is still reached from hand. An Edict is normally put into play
with an Open action, and focusing it instead is the only way its Focus Effect happens, because any
card in hand is a focus source.

## A consequence for the winner or the loser

Who won is not known until the duel is decided, so a consequence waits for `DUEL_CONSEQUENCES` and
reads the outcome there:

```{literalinclude} ../../src/yasuki_core/engine/rules/cards/the_harbinger.py
:pyobject: _resolve_flashy_technique_winner
:language: python
```

{func}`~.decided_outcome` is the read for a card that wants winners or losers, and
{func}`~.decided_duel` for one that also needs the record, to name a duelist. A card that created
the duel uses {func}`~.duel_decided_by` instead, which matches the duel against the card's own id:
a challenge that did not happen leaves the consequence held, and without the match it resolves off
whatever duel ends next.

A duel both Personalities lost has no winner at all, so a handler reading `winners` has to cope with
it being empty. {class}`~.BothLoseTheDuel` is how a card produces that outcome, and it is recorded
on the duel and read once, as the duel is decided.

## Reacting to a duel's time points

Every step a duel announces is a point a card may react at, and each one opens a round for
Responses. The events are in {mod}`yasuki_core.engine.rules.vocabulary.game_events`:
{class}`~.DuelDeclared`, {class}`~.CardFocused`, {class}`~.StrikeDeclared`,
{class}`~.FocusedCardsRevealed`, {class}`~.FocusEffectsResolved`, {class}`~.DuelResolved` and
{class}`~.DuelEnded`.

A card cannot yet ask which window it is in. {class}`~.DuelStep` reads `FOCUSING` for the
declaration, every focus and the window after the strike, so a Response that needs a narrower
moment reads the latest of those events out of `game.turn_events`. {card}`Poisoned Weapon` does
exactly that, because the step enum has no member between the reveal and the resolution.

## Where the rules live

`src/yasuki_core/engine/rules/duel/` holds the record, the focusing rules, the procedure, the
resolution and the Focus Effect registry. What may be focused belongs to the arc rather than to the
duel, behind {class}`~.FocusProcedure` on {mod}`yasuki_core.ruleset`.
