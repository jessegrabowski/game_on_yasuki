# Development Guide

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
# Install hooks (once)
pre-commit install

# Run on all files
pre-commit run --all
```

## Project Structure

```
src/
├── yasuki_core/          # Game engine and data layer
│   ├── engine/           #   Players, zones
│   ├── game_pieces/      #   Cards, decks, constants
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

## Architecture

**Dependency graph:** `yasuki_core ← yasuki_web`, `yasuki_core ← yasuki_gui`.
No dependency between web and gui.

**Key patterns:**
- Cards are frozen dataclasses with `object.__setattr__` state transitions
- Zones enforce capacity rules (e.g., ProvinceZone holds exactly 1 card)
- GUI separation: `FieldView` renders, `Controller` handles interaction
- Database stores card definitions; game state lives in memory

## Adding a Card Set

1. Place set images in `sets/<set_name>/` (one `.png` per card)
2. Add set metadata to `src/yasuki_core/assets/database/set_info.json`
3. Run `pixi run install-db --force` to re-seed

## Contributing

1. Fork the repo and create a feature branch
2. Install dev dependencies: `pixi install`
3. Install pre-commit hooks: `pre-commit install`
4. Make your changes and add tests
5. Run `pixi run test` and `pre-commit run --all`
6. Open a pull request
