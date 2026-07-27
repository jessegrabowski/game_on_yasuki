# Setup Guide

## Requirements

- Python 3.12+
- PostgreSQL 13+
- macOS, Linux, or Windows with X11/Wayland support

## Install Pixi

[Pixi](https://pixi.sh) manages both conda and PyPI dependencies.

```bash
# macOS / Linux
curl -fsSL https://pixi.sh/install.sh | bash

# Windows (PowerShell)
iwr -useb https://pixi.sh/install.ps1 | iex
```

## Install Dependencies

```bash
pixi install
```

This installs Python 3.12, psycopg (v3), Pillow, Tk, FastAPI, and all dev tools
from conda-forge and PyPI.

**Alternative (pip, server only):**

```bash
pip install -e ".[all]"
```

This installs the core library and the web server (`web` extra), but **not** the
desktop client: Tk is a conda/system dependency pip cannot provide, and the `all`
extra omits `reportlab`. Use the Pixi environment above to run the GUI.

## Install PostgreSQL

**macOS:**

```bash
brew install postgresql@16
brew services start postgresql@16
```

**Ubuntu / Debian:**

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Windows:**

Download from https://www.postgresql.org/download/windows/ and follow the
installer wizard.

**Verify:**

```bash
psql --version
```

## Create and Seed the Database

```bash
createdb yasuki
pixi run install-db
```

This assumes PostgreSQL is already running on localhost and your user can access it
without a password (check with `pg_isready`). `createdb` creates the database;
`install-db` only populates an existing one. If `createdb` reports that `yasuki`
already exists, skip it. `install-db` is do-nothing-on-conflict, so to reload card
data into an already-seeded database, add `--force` (see the flag table below).

For custom setups:

```bash
# Explicit DSN
pixi run install-db --dsn "postgresql://user:pass@host:5432/yasuki"

# Or via environment variable
export YASUKI_DATABASE_URL="postgresql://user:pass@host:5432/yasuki"
pixi run install-db
```

### Install flags

| Flag | Effect |
|------|--------|
| `--force` | Reapply the schema and reload data even if the tables already exist |
| `--skip-sets` | Skip set metadata import |
| `--skip-cards` | Skip card data import |
| `--cards PATH` | Override the per-set card YAML directory (default: `src/yasuki_core/assets/database/sets/`) |
| `--sets PATH` | Override the set-info YAML (default: `src/yasuki_core/assets/database/set_info.yaml`) |
| `--images PATH` | Override the per-set image-manifest directory (default: `src/yasuki_core/assets/database/images/`) |
| `--schema PATH` | Override the schema SQL file (default: `src/yasuki_core/assets/database/schema.sql`) |

## Card Set Images

Card images (~8 GB) are not checked into version control. Place or symlink them at
`sets/` in the repository root, or set the `YASUKI_SETS_DIR` environment variable:

```bash
export YASUKI_SETS_DIR=/path/to/your/sets
```

The game works without them — generic card-type images are bundled in the package.

## Next Steps

- [Run the desktop client](running.md)
- [Run with Docker](docker.md)
- [Contributing guide](../contributing/index.md)
