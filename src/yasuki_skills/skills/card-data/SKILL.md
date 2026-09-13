---
name: card-data
description: >
  Use this whenever you work on card data or the card database — editing a card's text/stats/printings,
  adding a set, issuing an erratum, adding card art/images, changing the Postgres schema, or the install
  pipeline that loads the committed YAML into the DB — and read it first, since the YAML is the source of
  truth (not the DB) and the reload and errata rules are easy to get wrong. Covers the file-first data
  model (assets/database/ YAML as source of truth), the cards/prints/errata/images schema, and the read
  path in database.py. The account/user database is separate — see the accounts skill.
---

# Card data & the card database

## Where it lives

- `src/yasuki_core/assets/database/` — the **source of truth** (committed YAML + schema):
  `sets/<slug>.yaml` (card text/stats/printings/errata), `images/<slug>.yaml` (image manifests),
  `set_info.yaml`, `counters.yaml`, `schema.sql`
- `src/yasuki_core/install/` — the loader: `install_db`, `yaml_to_sql`, `images_to_sql`, `sets_to_sql`
- `src/yasuki_core/database.py` — the card read/query path; `paths.py` — asset locations

## What it does

The committed YAML is authoritative; `install/` loads it into PostgreSQL (a derived cache). Reload after
edits with `pixi run install-db --force` (plain `install-db` is do-nothing-on-conflict). The schema:

- `cards` — one row per *logical* card, PK `card_id` (a title slug); canonical stats + `rules_text`.
- `prints` — one row per *physical printing* (`card_id` FK, `set_id` FK, `printing_id` within-card).
- `print_images` — images attach to **printings** (`role` front/back/alt, `sha256`, `path`).
- `card_revisions` — errata as a **revision time-axis** on the logical card (0 = original, highest =
  current), orthogonal to printings.
- Junctions off `card_id` (cascade): `card_clans`, `card_card_types`, `card_decks`, `card_keywords`.
- `counters` + `card_grants_counter`; `card_creates` (spawnable tokens); `l5r_sets`, `formats`,
  `card_legalities`/`print_legalities`.

Must-knows: canonical `cards.rules_text` follows the **most-recent-printing** rule with errata folded on
top; `prints.rules_text` is a per-printing override (NULL → fall back to the card's text); the current
erratum is mirrored onto the `cards` row so ordinary reads need no join to `card_revisions`. Counters are
scalar host state, **not** cards. Flip cards self-reference via `cards.back_card_id` (`is_back` flag).
Image *bytes* are never committed — they live in an R2 bucket + a gitignored local `sets/` cache.

## How it fits the big picture

This data feeds everything: `factory` builds the frozen card models from these rows at setup (see the
`game-pieces` skill), and `search` queries this schema (see the `search` skill). The engine itself never
touches the DB — cards are resolved up front, then the engine works purely in memory. The **accounts**
database is entirely separate (see the `accounts` skill).

Full narrative: `docs/design/database.md` is the most complete design doc, and it is worth reading
before editing card data. `docs/contributing/the_card_data.md` is the shorter card-author view of
the same thing, and it covers the derived `card_id`, which appears nowhere in the YAML.
