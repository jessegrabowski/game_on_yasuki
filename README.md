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

| Guide | Description |
|-------|-------------|
| [Setup](docs/setup.md) | Installation — PostgreSQL, Pixi, database seeding, card images |
| [Running](docs/running.md) | Launch the GUI, start the API server, configuration |
| [Docker](docs/docker.md) | Run PostgreSQL and the API in containers |
| [Development](docs/development.md) | Tests, linting, project structure |
| [Search syntax](docs/search-syntax.md) | Scryfall-style card search query language |
| [API reference](docs/api.md) | REST endpoints and WebSocket protocol |

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
