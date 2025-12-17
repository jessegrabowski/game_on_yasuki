# Game on, Yasuki!

Online client for playing classic Legend of the Five Rings (L5R) card game. This repository contains the game engine, GUI client, and supporting assets needed to run the game locally.

## System Requirements

- Python 3.12 or later
- PostgreSQL 13 or later
- macOS, Linux, or Windows with X11/Wayland support
- Conda or Mamba (recommended) for dependency management

## Installation

### Step 1: Install PostgreSQL

PostgreSQL is required for storing card data and game metadata.

**macOS:**

```bash
# Using Homebrew
brew install postgresql@16

# Start PostgreSQL service
brew services start postgresql@16
```

**Ubuntu/Debian Linux:**

```bash
sudo apt update
sudo apt install postgresql postgresql-contrib

# Start PostgreSQL service
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Windows:**

Download the installer from the official PostgreSQL website:
https://www.postgresql.org/download/windows/

Run the installer and follow the setup wizard. Note the password you set for the `postgres` user during installation.

**Verify Installation:**

```bash
psql --version
```

You should see output like `psql (PostgreSQL) 16.x`.

### Step 2: Create the Database

After PostgreSQL is installed and running, create a database for the application.

**macOS/Linux:**

```bash
# Create database (using your system user)
createdb l5r
```

**Windows (or if createdb is not in PATH):**

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE l5r;

# Exit psql
\q
```

### Step 3: Install Python Dependencies

This project uses conda for environment management. If you don't have conda installed, download Miniconda from:
https://docs.conda.io/en/latest/miniconda.html

Alternatively, use Mamba for faster dependency resolution:
https://mamba.readthedocs.io/

**Create and activate the environment:**

```bash
# Using conda
conda env create -f environment.yaml
conda activate game-on-yasuki-dev

# Or using mamba (faster)
mamba env create -f environment.yaml
mamba activate game-on-yasuki-dev
```

The `environment.yaml` file includes all required dependencies: Python 3.12, pytest, pydantic, Pillow, psycopg2, and pre-commit hooks.

**Alternative: pip installation**

If you prefer pip, you can install the package in development mode:

```bash
pip install -e .
```

However, conda/mamba is recommended for easier environment management and reproducibility.

### Step 4: Initialize the Database

Game data is stored under `app/assets/database/`. The installation script will apply the schema and import all card data.

**Basic installation:**

```bash
python -m app.install.install_db
```

This assumes PostgreSQL is running on localhost with a database named `l5r` that your current user can access without a password.

**Custom database connection:**

If your PostgreSQL setup differs, specify a connection string:

```bash
# Using DSN format
python -m app.install.install_db --dsn "postgresql://localhost/l5r"

# With authentication
python -m app.install.install_db --dsn "postgresql://username:password@localhost:5432/l5r"

# Or set an environment variable
export L5R_DATABASE_URL="postgresql://localhost/l5r"
python -m app.install.install_db
```

**Installation flags:**

- `--force` — Drop and recreate the schema even if tables already exist
- `--skip-sets` — Skip importing set metadata (faster iteration during development)
- `--skip-cards` — Skip importing card data (faster iteration during development)
- `--cards PATH` — Override path to cards.json
- `--sets PATH` — Override path to set_info.json
- `--schema PATH` — Override path to schema.sql

The installer will validate that PostgreSQL is installed, the database exists, and all required asset files are present. If any prerequisites are missing, it will provide specific instructions for resolution.

## Running the Game

Once dependencies are installed and the database is initialized, launch the game client:

```bash
# Python launcher
python play.py

# With debug logging
python play.py --debug

# Shell launcher (Unix/macOS)
./play.sh

# Or as a module
python -m app.gui
```

## Development

### Running Tests

Execute the test suite with pytest:

```bash
pytest tests/
```

For coverage reporting:

```bash
pytest tests/ --cov=app --cov-report=html
```

### Code Quality

This project uses pre-commit hooks with ruff for linting and formatting:

```bash
# Install pre-commit hooks
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

### Debugging

Enable debug logging to see detailed information about database queries, GUI initialization, card loading, and error tracebacks:

```bash
python play.py --debug
```

Debug output includes:
- Database connection and query execution
- GUI component initialization and event handling
- Card caching and preview generation
- Full exception tracebacks with context

## Database Management

To update card data or schema changes:

```bash
# Update with existing data intact
python -m app.install.install_db

# Force schema recreation (drops all data)
python -m app.install.install_db --force
```

Connection strings can use either format:
- URI format: `postgresql://[user[:password]@][host][:port]/database`
- Keyword format: `"dbname=l5r user=postgres password=secret host=localhost"`

## Project Structure

- `app/` — Source code
  - `engine/` — Game logic and rules engine
  - `game_pieces/` — Card and deck representations
  - `gui/` — Tkinter-based client interface
  - `assets/` — Card database, images, and schema
  - `install/` — Database installation utilities
- `tests/` — Test suite mirroring source structure
- `environment.yaml` — Conda environment specification
- `pyproject.toml` — Project configuration and dependencies
- `play.py` — Application launcher script

## License

This project is for personal and educational use. Legend of the Five Rings is a trademark of Fantasy Flight Games.
