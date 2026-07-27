# Game on, Yasuki!

Online client for playing the classic Legend of the Five Rings (L5R) collectible
card game — with a desktop GUI, card database, deck builder, and multiplayer
server.

## Quick Start

```bash
# Install dependencies
pixi install

# Create and seed the card database
createdb yasuki
pixi run install-db

# Play
pixi run play
```

No PostgreSQL? Use Docker instead:

```bash
pixi run docker-up                                                    # start DB
YASUKI_DATABASE_URL=postgresql://yasuki:yasuki@localhost:5432/yasuki pixi run play  # play
```

## What's in the Box

| Package | Description |
|---------|-------------|
| **`yasuki_core`** | Game engine, card models, database, search, card data |
| **`yasuki_web`** | FastAPI server — multiplayer rooms, deck builder SPA |
| **`yasuki_gui`** | Tkinter desktop client — board, drag & drop, deck builder |

Dependency direction: `yasuki_core ← yasuki_web`, `yasuki_core ← yasuki_gui`.

## Documentation

Full documentation is hosted at **[game-on-yasuki.readthedocs.io](https://game-on-yasuki.readthedocs.io)** —
narrative guides plus an auto-generated API reference for all three packages.

| Guide | Description |
|-------|-------------|
| [Setup](docs/getting_started/setup.md) | Installation — PostgreSQL, Pixi, database seeding, card images |
| [Running](docs/getting_started/running.md) | Launch the GUI, start the API server, configuration |
| [Docker](docs/getting_started/docker.md) | Run PostgreSQL and the API in containers |
| [Database & card data](docs/design/database.md) | How card data, printings, errata, and images are stored |
| [Web app API](docs/design/web-app.md) | REST endpoints and WebSocket protocol |
| [Search syntax](docs/design/search.md) | Scryfall-style card search query language |
| [Contributing](docs/contributing/index.md) | Tests, linting, project structure, workflow |

Build the docs locally with `pixi run docs-build` (output in `docs/_build/html`), or
serve them at <http://localhost:8080> with `pixi run docs-serve`.

## Contributing

This is a personal, educational project, but interest is welcome. To contribute:

1. Fork the repo and create a feature branch
2. Install dependencies and hooks: `pixi install && pre-commit install`
3. Make your changes and add tests
4. Run `pixi run test` and `pre-commit run --all`
5. Open a pull request

## License

This project is for personal and educational use. Legend of the Five Rings is a
trademark of Fantasy Flight Games.
