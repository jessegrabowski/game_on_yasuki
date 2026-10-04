---
name: card-vocabulary
description: >
  Use this for what a card is able to say: the effects a handler returns, the events it can react
  to, the decisions it can ask for, how costs are paid, and how a card's stats and gold are
  computed. Fires on "add an effect", "what effect do I return", "the vocabulary cannot express
  this", "add a new game event", "how do costs work", "why is this card's Force wrong", "add a
  keyword", "why did my Focus Effect not resolve", "the duel does not end", and on any engine change
  under rules/vocabulary, rules/abilities, rules/stats, rules/gold, rules/units, rules/battle or
  rules/duel. Read it before inventing a way to say something, because the vocabulary is a closed
  set of dataclasses that the effect applier and the projection layer both have to understand, and a
  handler that mutates the board instead of returning an effect breaks undo. This skill covers what
  a handler may return; writing the handler for a printed card is implementing-a-card, and the turn
  machine that calls it is turns-and-actions.
---

# The card vocabulary

## Where it lives

- `src/yasuki_core/engine/rules/vocabulary/`: the closed sets a card speaks in: `actions.py`,
  `decisions.py`, `game_events.py`, `keywords.py`, `modifiers.py`, `segments.py`, `victory.py`,
  `work.py`
- `src/yasuki_core/engine/rules/effects.py`: the effect dataclasses and what applying one does
- `src/yasuki_core/engine/rules/triggers.py`: the cascade: an effect commits, the handlers its
  events fire resolve completely, and only then does the next effect apply
- `src/yasuki_core/engine/rules/abilities/`: `model.py`, `registry.py`, `activation.py`,
  `costs.py`, `invest.py`, `strategy.py`, `idioms.py`
- `src/yasuki_core/engine/rules/stats/` and `rules/gold/`: effective values and the gold economy
- `src/yasuki_core/engine/rules/units/`, `rules/battle/`: unit composition and battle records
- `src/yasuki_core/engine/rules/duel/`: the duel procedure, its focusing seam and the Focus Effect
  registry

## What it does

A handler never mutates the board. It returns effects, and the applier commits them. That is what
makes the replay log a complete account of the game, and undo possible at all. Anything a card can
express is a dataclass in this vocabulary.

The vocabulary grows by composition. Decompose the text into rule-level verbs and find the existing
term for each before adding one. A new term is warranted only for a primitive nothing composes to.
Name it for the rule's verb, never for a card or mechanic, and in the same change replace every
bespoke path that did its job. `docs/design/build_from_the_vocabulary.md` is the procedure, with the
Legacy, Edict and duel-consequence cases worked through. Read it before adding an effect, decision,
event, moment or registry.

Effects in a returned list happen in the order they are written, and what each one sets off resolves
before the next applies (CR 20F, Timing), so a step that follows a reaction is just the next effect.
Text that acts on several cards at once, one phrase over many cards, returns those effects inside a
`Simultaneously`, so nothing reacts to any of them until all have happened. A group holds off
triggers only. The state-based rules are still enforced after each member, so wrapping two effects
in a group does not let both commit before the board is judged. Two effects the text joins with "to"
("discard a card to draw a card"), or a clause that depends on an earlier one ("if you put a Ring
into play, ..."), are a `To`, so the second applies only if the first actually happened.
A trait acting before a card is destroyed ("before this card is destroyed", Yu) answers
`Destroying`, which is announced before the destruction commits unless a negation in force will stop
it. A group's destructions are announced together. A printed Yu registers with `register_yu`, which
applies the datasheet's conditions for when Yu resolves, and a Yu one card gives others ("Your
Followers at this battlefield have, 'Yu: ...'") with `register_granted_yu`, whose `reaches` names
the cards that have it. A granted trigger fires as the reached card's own.
`docs/design/systems/effects.md` has the rules and the CR lines behind them.

Stats are computed rather than stored: a card's printed value is the starting point, and grants and
modifiers layer over it. Gold is the same shape on the economy side. A card that appears to have the
wrong number almost always has a handler contributing to the calculation rather than a wrong value
in the data.

## What checks it

- The suite, which covers every implemented card against the vocabulary it uses
- `registration-audit` (pre-commit, and a test in CI): every registered id names a real card
- `docs-api` (pre-commit): the API pages match the source, so a renamed effect fails the build

## How it fits

`docs/design/card_vocabulary.md` lists the vocabulary itself. Then one page per system:
`effects.md`, `triggers-and-the-cascade.md`, `abilities-and-costs.md`, `stats.md`, `gold.md`,
`decisions-and-resumption.md`, `looking-at-cards.md`, `units-and-attachments.md`, `battle.md`,
`duels.md` and `the-imperial-favor.md`, all under `docs/design/systems/`.

Handlers for printed cards are the `implementing-a-card` skill. The turn machine that fires events
and offers actions is `turns-and-actions`.
