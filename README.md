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

This project uses [Pixi](https://pixi.sh) for environment management. Pixi handles both conda and PyPI dependencies seamlessly.

**Install Pixi:**

```bash
# macOS/Linux
curl -fsSL https://pixi.sh/install.sh | bash

# Windows (PowerShell)
iwr -useb https://pixi.sh/install.ps1 | iex
```

**Install dependencies:**

```bash
pixi install
```

This installs all required dependencies from conda-forge (Python 3.12, psycopg2, Pillow, tk) and PyPI (FastAPI, uvicorn).

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
pixi run install-db
```

This assumes PostgreSQL is running on localhost with a database named `l5r` that your current user can access without a password.

**Custom database connection:**

If your PostgreSQL setup differs, specify a connection string:

```bash
# Using DSN format
pixi run install-db -- --dsn "postgresql://localhost/l5r"

# With authentication
pixi run install-db -- --dsn "postgresql://username:password@localhost:5432/l5r"

# Or set an environment variable
export L5R_DATABASE_URL="postgresql://localhost/l5r"
pixi run install-db
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
# Using Pixi
pixi run play

# With debug logging
pixi run play -- --debug

# Or directly with Python (if in pixi shell)
pixi shell
python play.py
```

## Docker (Skip PostgreSQL Installation)

Docker lets you run PostgreSQL without installing it natively. The GUI still runs
on your host machine — only the database lives in a container.

### Quick Start: Database Only

```bash
# Start PostgreSQL and seed the card database (first run takes a moment)
docker-compose up db db-init

# Once "l5r-db-init exited with code 0" appears, the database is ready.
# Leave this terminal running (or add -d to run in background).
```

Then launch the GUI normally, pointing at the containerized database:

```bash
L5R_DATABASE_URL=postgresql://l5r:l5r@localhost:5432/l5r pixi run play
```

### API Server (Multiplayer)

To run the FastAPI backend for multiplayer:

```bash
docker-compose --profile api up -d db db-init api
```

The API will be available at `http://localhost:8000`. Interactive docs at
`http://localhost:8000/docs`.

### Managing the Database

```bash
# Stop everything
docker-compose down

# Stop and delete all card data (fresh start)
docker-compose down -v
```

## Development

### Running Tests

Execute the test suite with pytest:

```bash
pixi run test
```

For coverage reporting:

```bash
pixi run test -- --cov=app --cov-report=html
```

### Code Quality

This project uses pre-commit hooks with ruff for linting and formatting:

```bash
# Install pre-commit hooks
pixi run pre-commit install

# Run manually on all files
pixi run lint
```

### Debugging

Enable debug logging to see detailed information about database queries, GUI initialization, card loading, and error tracebacks:

```bash
pixi run play -- --debug
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
