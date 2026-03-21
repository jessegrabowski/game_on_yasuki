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

This installs Python 3.12, psycopg2, Pillow, Tk, FastAPI, and all dev tools from
conda-forge and PyPI.

**Alternative (pip only):**

```bash
pip install -e ".[all]"
```

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

This assumes PostgreSQL is running on localhost and your user can access it without
a password. For custom setups:

```bash
# Explicit DSN
pixi run install-db -- --dsn "postgresql://user:pass@host:5432/yasuki"

# Or via environment variable
export YASUKI_DATABASE_URL="postgresql://user:pass@host:5432/yasuki"
pixi run install-db
```

### Install flags

| Flag | Effect |
|------|--------|
| `--force` | Drop and recreate schema (destroys existing data) |
| `--skip-sets` | Skip set metadata import |
| `--skip-cards` | Skip card data import |
| `--cards PATH` | Override path to `cards.json` |
| `--sets PATH` | Override path to `set_info.json` |
| `--schema PATH` | Override path to `schema.sql` |

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
- [Development guide](development.md)
