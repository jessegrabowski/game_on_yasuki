---
name: implementing-a-card
description: >
  Use this when you are making a printed card work: choosing which hook its text wants, writing the
  trigger or activated ability, registering it, or editing anything under
  src/yasuki_core/engine/rules/cards/. Fires on "implement this card", "model this card", "why does
  my handler never fire", "which hook does this wording want", "where does this card go", and on any
  request naming a card title and asking for behavior. Read it before writing the handler rather
  than after: the card id is derived rather than written, the module a card belongs in is decided by
  its first printing, and a handler keyed on a typo registers happily and never fires. This skill
  covers writing the handler. What a handler may return -- the effects, triggers, costs and stat
  vocabulary -- is the card-vocabulary skill, the machinery that calls it is turns-and-actions, and
  the card's text, stats and printings are card-data.
---

# Implementing a card

## Where it lives

`src/yasuki_core/engine/rules/cards/<set>.py`, one module per set, mirroring
`src/yasuki_core/assets/database/sets/<set>.yaml`. A card is implemented once, in the set that
printed it first, and `tests/yasuki_core/engine/rules/test_card_placement.py` enforces that. A new
set module needs a line in `src/yasuki_core/engine/rules/cards/__init__.py` or none of its cards
register at all.

Everything one card does goes in one block under a `# --- Card Name ---` header, in card-id order:
its triggers, target predicates, effects helper and registration. Functions are named
`_<card id>_<role>`.

Tests go beside the code, at `tests/yasuki_core/engine/rules/cards/test_<set>.py`.

## What it does

The card's id is derived from its printed title by `card_slug`, not written down anywhere you can
edit. It is the key every registry uses, and
`src/yasuki_core/assets/database/card_ids.txt` is the committed list of all of them.

Read the card's text, find the shape, pick the hook. The table in
`docs/contributing/adding_a_card.md` maps printed wording to hook with an example card for each --
start there rather than grepping for a registry that looks close.

A handler never mutates the board. It returns effects, and the trigger machinery commits them.

Two failure modes are worth knowing before you write anything. A handler keyed on a misspelled id
registers, never fires, and raises nothing; the `registration-audit` pre-commit hook is what catches
it, and it names the nearest real id. And every copy of a card in play runs the same trigger, so a
trigger about "this card" needs to compare the event's card id against its own or all three copies
act.

## What checks it

- `card-layout` (pre-commit) -- header per card, card-id order, one block per card, functions named
  for their card and role. Runs on the modules your commit touches.
- `registration-audit` (pre-commit, and a test in CI) -- every registered id names a real card.
- `card-index` (pre-commit, and CI) -- `card_ids.txt` matches the set YAML.
- The suite -- every implemented card is covered, and that is not an accident.

## How it fits

Start at `docs/contributing/adding_a_card.md`, the reference for which hook a wording wants. Then,
in reading order for a first card: `docs/contributing/what_a_card_is.md` for the three things called
a card, `docs/contributing/the_card_data.md` for how the YAML is authored and the id derived,
`docs/contributing/reading_card_text.md` for the templating conventions that look like rules and are
not, `docs/contributing/reacting_to_events.md` for a worked trigger, and
`docs/contributing/holdings_and_gold.md` for a worked gold handler.

The systems behind them are `docs/design/systems/triggers-and-the-cascade.md`,
`docs/design/systems/stats.md`, `docs/design/systems/gold.md` and
`docs/design/systems/registration-and-the-audit.md`. A card the bots cannot evaluate is covered by
`docs/design/systems/bots-and-policies.md`.
