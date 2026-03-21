# Running the Game

## Desktop Client (Tkinter)

```bash
pixi run play
```

With debug logging:

```bash
python play.py --debug
```

Or as a Python module:

```bash
python -m yasuki_gui
```

## API Server

```bash
pixi run api
```

This starts the FastAPI server on `http://localhost:8000`.

- Interactive docs: `http://localhost:8000/docs`
- Deck builder: `http://localhost:8000/deck-builder`
- Health check: `http://localhost:8000/health`

## Configuration

### Database Connection

The application checks these sources in order:

1. `YASUKI_DATABASE_URL` environment variable
2. `DATABASE_URL` environment variable (PaaS convention)
3. `database.dsn` in `config.yaml` (GUI only)
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
```

### Debug Logging

Debug output includes database queries, GUI events, card loading, and full
exception tracebacks:

```bash
python play.py --debug
```
