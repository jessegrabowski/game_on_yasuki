---
name: card-data
description: >
  Use this when you are changing what a card *is* rather than what it does: correcting a title,
  text, stat or keyword, adding a set, issuing an erratum, adding card art or an image manifest,
  touching the PostgreSQL schema, or working on the pipeline that loads the committed YAML into the
  database. Fires on "add a set", "fix this card's text", "the database has the wrong", "issue an
  erratum", "add card images", "reload the card database", and on any question about where card data
  lives. Read it first, because the YAML is the source of truth and the database is a cache that
  will not pick up an edit without --force, and because a card's id is derived from its title, so
  editing a title silently orphans every handler keyed on the old one. Covers
  src/yasuki_core/assets/database/, src/yasuki_core/install/ and database.py. Implementing a card's
  behavior is the implementing-a-card skill; the user and deck database is accounts.
---

# Card data and the card database

## Where it lives

- `src/yasuki_core/assets/database/sets/`: one YAML file per set, the source of truth
- `src/yasuki_core/assets/database/set_info.yaml`, `set_alias.yaml`, `counters.yaml`: set metadata
- `src/yasuki_core/assets/database/images/`: one image manifest per printing
- `src/yasuki_core/assets/database/card_ids.txt`: the generated index of every card id
- `src/yasuki_core/assets/database/schema.sql`: the PostgreSQL schema
- `src/yasuki_core/install/`: the load pipeline: `install_db.py`, `yaml_to_sql.py`,
  `sets_to_sql.py`, `images_to_sql.py`, `card_index.py`, `registration_audit.py`
- `src/yasuki_core/database.py`: the read path everything else goes through

## What it does

The committed YAML is the source of truth and PostgreSQL is a derived cache. `pixi run install-db`
loads one into the other and does nothing where a row already exists, so an edit to a set file is
invisible until `pixi run install-db --force`. Fixing a card by editing the database is always
wrong: the next reload overwrites it.

A card's id is derived from its printed title by `card_slug` rather than written down. Renaming a
card therefore renames its id, which orphans every handler, token and rulebook exception keyed on
the old one. `card_ids.txt` is the committed index of all of them; regenerate it with
`pixi run card-index` after changing set YAML and commit the result.

An erratum appends to the card's revision history and mirrors the newest text onto the card itself,
so the old text stays readable rather than being overwritten. Errata art is an ordinary card image:
a file in the set's image directory and an entry in that printing's manifest.

## What checks it

- `card-index` (pre-commit, and a test): `card_ids.txt` matches the set YAML, in both directions
- `registration-audit` (pre-commit, and a test in CI): every registered handler names a real card
- The `{card}` role in the docs: a card title deriving to an id the index does not hold fails the
  documentation build

## How it fits

`docs/design/database.md` is the reference: the schema, the two planes of metadata and image bytes,
the reload rules and how errata are recorded. `docs/contributing/the_card_data.md` covers authoring
a card's YAML and how its id is derived. `docs/getting_started/setup.md` is how to get a database at
all.

The behavior a card's text implies is the `implementing-a-card` skill, and the query language that
reads these rows is `card-search`. The `accounts` skill covers the separate user database, which is
kept apart so that reseeding cards can never reach user data.
