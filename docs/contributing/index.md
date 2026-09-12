# Contributing

Game on, Yasuki! is a personal, educational project, but contributions are welcome.

## Workflow

1. Fork the repo and create a feature branch.
2. Install dependencies and hooks: `pixi install && pre-commit install`.
3. Make your changes and add tests.
4. Run `pixi run test` and `pre-commit run --all`.
5. Open a pull request.

New to the codebase? Start with [Setup](../getting_started/setup.md), then read
[Design & Architecture](../design/index.md) for how the pieces fit together.

Implementing a card is its own workflow: see [Adding a Card](adding_a_card.md).

## Running Tests

```bash
# Python tests
pixi run test

# JS deck builder tests
pixi run test-js

# With coverage
pixi run test -- --cov=yasuki_core --cov=yasuki_gui --cov=yasuki_web --cov-report=html
```

## Linting

This project uses pre-commit with ruff:

```bash
pre-commit install       # once
pre-commit run --all     # run on all files
```

## Project Structure

```
src/
├── yasuki_core/          # Game engine and data layer
│   ├── engine/           #   Table state, zones, players, and the rules/ subpackage
│   │   └── rules/        #   State, flow, actions, decisions, abilities, effects, triggers
│   ├── game_pieces/      #   Cards, decks, counters, constants
│   ├── search/           #   Scryfall-style query parser
│   ├── install/          #   Database bootstrap
│   ├── database.py       #   PostgreSQL queries
│   ├── paths.py          #   Asset path configuration
│   └── assets/           #   Bundled data + images
│
├── yasuki_web/           # FastAPI web server
│   ├── main.py           #   App, CORS, static mounts
│   ├── cards.py          #   Card search API
│   ├── rooms.py          #   Game room management
│   ├── websocket.py      #   Multiplayer websockets
│   ├── schemas.py        #   Pydantic message schemas
│   └── static/           #   Deck builder SPA
│
└── yasuki_gui/           # Tkinter desktop client
    ├── __main__.py       #   Entry point
    ├── field_view.py     #   Game board rendering
    ├── controller.py     #   User interaction
    ├── services/         #   Drag-drop, hit-testing, actions
    ├── ui/               #   Dialogs, deck builder, menus
    └── visuals/          #   Sprite and zone rendering
```

Tests mirror this structure under `tests/yasuki_core/`, `tests/yasuki_web/`,
`tests/yasuki_gui/`.

## Adding a Card Set

Card data is committed YAML — the full workflow (set YAML, image manifests, errata) lives in
[Database & card data](../design/database.md). The short version:

1. Add the set's card data to `src/yasuki_core/assets/database/sets/<slug>.yaml` and its metadata to
   `set_info.yaml`.
2. Add the image manifest at `src/yasuki_core/assets/database/images/<slug>.yaml`.
3. Reload the database: `pixi run install-db --force`.
4. Regenerate the card-id index: `pixi run card-index`, and commit the result.

## The Card-Id Index

`src/yasuki_core/assets/database/card_ids.txt` lists every card id in the set YAML, one per line. It
is generated, not hand-edited, and committed so that checks needing to know whether a card exists can
read a file in a millisecond instead of reparsing 131 YAML files in about a second and a half.

Three things read it:

- A **pre-commit hook** (`registration-audit`) asserts that every id the engine registers a handler on
  names a real card. A handler keyed on a typo registers happily, never fires, and raises nothing —
  the card is simply dead. The hook reports the registry, the id, and the nearest real id:

  ```
  abilities: no card has the id 'milet_farm' — did you mean millet_farm?
  ```

  Fix the id. The hook needs the project environment, so it does not run in CI; the same check runs
  there as a test.

- The **`{card}` role** in the docs turns a printed card title into a link to that card on the live
  site, deriving the id the same way the YAML loader does. A title deriving to an id the index does
  not hold is reported with its file and line, and `docs-build` runs under `-W`, so the build fails
  rather than shipping a link to a 404.

  ```markdown
  {card}`Exquisite Nagamaki of the Fox Clan`
  ```

- Two **tests**, which assert that every token a card creates and every card a rulebook exception
  names is a real card.

Regenerate it with `pixi run card-index` after changing set YAML, and commit the result.
`test_the_committed_index_matches_the_card_yaml` reparses the YAML and diffs it against the
committed file, in both directions, and names the command to run when it fails. It costs about a
second, which is why it is the only thing that pays that price and every other reader gets the
index.

```{toctree}
:hidden:

adding_a_card
what_a_card_is
reading_card_text
the_card_data
holdings_and_gold
stats_and_costs
an_ability
several_abilities
reacting_to_events
asking_a_question
attachments
battle_cards
cards_outside_play
```
