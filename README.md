# Game on, Yasuki!

Online client for playing classic Legend of the Five Rings (L5R). This repo contains the
engine, GUI, and supporting assets needed to run the game locally.

## Requirements

- Python 3.12+
- PostgreSQL 13+ running locally with a database you can create/modify
- `psycopg2-binary` (installed automatically via `pip install -e .`)

Install Python dependencies with:

```bash
pip install -e .
```

## Bootstrapping the PostgreSQL database

Game data lives under `app/assets/database/`. A helper CLI seeds the database using
`schema.sql`, `cards.json`, and `set_info.json`.

1. Create a database (defaults assume one named `l5r`). For example:

   ```bash
   createdb l5r
   ```

2. Either export a DSN via `L5R_DATABASE_URL` or pass `--dsn` when running the installer. Example DSNs:
   - `postgresql://localhost/l5r`
   - `"dbname=l5r user=postgres password=secret"`

3. Run the installer:

   ```bash
   python -m app.install.install_db --dsn "postgresql://localhost/l5r"
   ```

The script will:

- Apply `app/assets/database/schema.sql` (dropping/recreating the schema if you pass `--force`).
- Import set metadata with `sets_to_sql.py`.
- Import all cards from `cards.json`.

### Useful flags

- `--force` – recreate the schema even if tables already exist (drops `public`).
- `--skip-sets` / `--skip-cards` – avoid re-importing large data sets when iterating.
- `--cards`, `--sets`, `--schema` – override the default asset paths.

Re-run the installer any time you refresh the raw data files. Use `--force` when the schema
changes, otherwise omit it to keep your existing data untouched.

## Running the Game

Once dependencies are installed and the database is set up, you can launch the game using any of these methods:

### Simple launcher scripts

```bash
# Python launcher
python play.py

# With debug logging
python play.py --debug

# Shell launcher (Unix/macOS)
./play.sh
```

### Run as a module

```bash
python -m app.gui
```

## Debugging

Use the `--debug` flag to enable detailed logging output:

```bash
python play.py --debug
```

This will show:
- Database queries and results
- GUI initialization steps
- Card loading and caching
- Preview updates and stat changes
- Error tracebacks with full context

## Running tests

```bash
pytest tets
```
