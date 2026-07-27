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
