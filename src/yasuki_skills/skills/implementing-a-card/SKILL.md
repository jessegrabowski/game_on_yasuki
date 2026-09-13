---
name: implementing-a-card
description: >
  Use this when you are making a printed card work: choosing which hook its text wants, writing the
  trigger or activated ability, registering it, or editing anything under
  src/yasuki_core/engine/rules/cards/. Fires on "implement this card", "model this card", "why does
  my handler never fire", "which hook does this wording want", "where does this card go", and on any
  request naming a card title and asking for behavior. Read it before you write the handler: the
  card id is derived rather than written down, the module a card belongs in is decided by its first
  printing, and a handler keyed on a typo registers happily and never fires. This skill covers
  writing the handler. The effects, triggers, costs and stat vocabulary a handler may return are the
  card-vocabulary skill, the machinery that calls it is turns-and-actions, and the card's text,
  stats and printings are card-data.
---

# Implementing a card

## Where it lives

`src/yasuki_core/engine/rules/cards/<set>.py`, one module per set, mirroring
`src/yasuki_core/assets/database/sets/<set>.yaml`. A card is implemented once, in the set that
printed it first, and `tests/yasuki_core/engine/rules/test_card_placement.py` enforces that. A new
set module needs a line in `src/yasuki_core/engine/rules/cards/__init__.py`, or none of its cards
register at all.

Everything one card does goes in one block under a `# --- Card Name ---` header, in card-id order:
its triggers, target predicates, effects helper and registration. Functions are named
`_<card id>_<role>`.

Tests go beside the code, at `tests/yasuki_core/engine/rules/cards/test_<set>.py`.

## What it does

`card_slug` derives the card's id from its printed title, and every registry keys on it.
`src/yasuki_core/assets/database/card_ids.txt` is the committed list of all of them.

Read the card's text, find the shape, pick the hook. The table in
`docs/contributing/adding_a_card.md` maps printed wording to hook with an example card for each.
Start there; grepping for a registry that looks close is how cards end up on the wrong one.

A handler never mutates the board. It returns effects, and the trigger machinery commits them.

A number printed on the card belongs in its YAML, and a handler reads it rather than repeating it:
a gold handler owns the whole amount the card produces, so it adds to `card.gold_production` instead
of restating it. Where the stat is missing from the data, the fix is the set file, which the
`card-data` skill covers. A printed number typed into code is a second copy of one the database
already holds.

Three failure modes are worth knowing before you write anything. A handler keyed on a misspelled id
registers, never fires, and raises nothing. The `registration-audit` pre-commit hook catches that one
and names the nearest real id. The second is quieter: every copy of a card in play runs the same
trigger, so a trigger about "this card" has to compare the event's card id against its own, or all
three copies act. The third passes every check in this repository: a printed stat hard-coded into a
handler produces the right number today and the wrong one after an erratum, and nothing fails.

## What checks it

- `card-layout` (pre-commit): header per card, card-id order, one block per card, functions named
  for their card and role. Runs on the modules your commit touches.
- `registration-audit` (pre-commit, and a test in CI): every registered id names a real card.
- `card-index` (pre-commit, and CI): `card_ids.txt` matches the set YAML.
- The suite: every implemented card is covered, and that is not an accident.

## How it fits

Start at `docs/contributing/adding_a_card.md`, the reference for which hook a wording wants. Then,
in reading order for a first card: `docs/contributing/what_a_card_is.md` for the three things called
a card, `docs/contributing/the_card_data.md` for how the YAML is authored and the id derived,
`docs/contributing/reading_card_text.md` for the templating conventions that look like rules and are
not, and `docs/contributing/reacting_to_events.md` for a worked trigger.

Then by what the card does: `an_ability.md` and `several_abilities.md` for activated abilities,
`asking_a_question.md` when the text says "choose" or "may", `holdings_and_gold.md` for a gold
handler, and `stats_and_costs.md` for whether a number needs a handler at all. Five pages cover the
kinds of card that need something other than the common shape: `attachments.md`, `battle_cards.md`,
`cards_outside_play.md`, `creating_cards.md` and `the_favor_and_the_court.md`.

Two pages are about what happens to a handler once it exists.
`docs/design/systems/registration-and-the-audit.md` covers how it binds to its card, and
`docs/design/systems/bots-and-policies.md` covers why a new ability is invisible to the bots until
someone says what it is worth.

The effects, triggers and costs a handler returns are the `card-vocabulary` skill. The machinery
that calls it is `turns-and-actions`. The card's text, stats and printings are `card-data`.
