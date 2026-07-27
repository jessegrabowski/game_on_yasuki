# Running the Game

Complete [Setup](setup.md) first — these commands assume an installed Pixi environment
and a created, seeded database.

## Desktop Client (Tkinter)

```bash
pixi run play
```

With debug logging:

```bash
pixi run python play.py --debug
```

Or as a Python module:

```bash
pixi run python -m yasuki_gui
```

## API Server

```bash
pixi run api
```

This starts the FastAPI server on `http://localhost:8000` (override the port with the
`PORT` environment variable).

- Interactive docs: `http://localhost:8000/docs`
- Deck builder: `http://localhost:8000/deck_builder`
- Health check: `http://localhost:8000/health`

## Configuration

The desktop client reads optional settings from a `config.yaml` at the repository root. It
does not exist by default; copy the template to create one:

```bash
cp config.yaml.example config.yaml
```

### Database Connection

The application checks these sources in order:

1. `YASUKI_DATABASE_URL` environment variable
2. `database.dsn` in `config.yaml` (GUI only)
3. `DATABASE_URL` environment variable (PaaS convention)
4. Default: `postgresql://localhost/yasuki`

### Card Images

Set images are loaded from `YASUKI_SETS_DIR` (default: `./sets/`). The game
falls back to generic card-type images when set images aren't available.

### GUI Hotkeys

Hotkeys can be customized in `config.yaml`:

```yaml
gui:
  hotkeys:
    bow: b
    flip: f
    invert: d
    fill: l
    destroy: c
    draw: r
    shuffle: s
    inspect: i
    view: v
```

### Debug Logging

Debug output includes database queries, GUI events, card loading, and full
exception tracebacks:

```bash
pixi run python play.py --debug
```
