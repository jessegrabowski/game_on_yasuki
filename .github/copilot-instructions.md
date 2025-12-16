# Game on, Yasuki! Copilot Instructions

## Overview

**Game on, Yasuki!**: Online client for playing classic Legend of the Five Rings (L5R) card game. Python 3.12+, uses Tkinter (GUI), FastAPI (future multiplayer), PostgreSQL (card database), Pydantic (schemas), PIL/Pillow (image handling), pytest.

## Design Principles

- **Game Engine**: Core game logic separated from GUI (in `app/engine/` and `app/game_pieces/`)
- **Immutable game pieces**: Cards use frozen dataclasses with explicit state transition methods
- **Zone-based architecture**: Game areas (hand, battlefield, provinces, discard) managed by specialized Zone classes
- **Object-oriented with functional patterns**: Core objects with clean interfaces; avoid deep inheritance hierarchies
- Use CLEAN code principles. Function and variable names should be descriptive. Code should be self-documenting.
- Docstrings use Numpy format. Typehints in docstrings should be human-readable: `x: list[str]` is *bad*, `x: list of str` is *good*.


### Key Architecture Decisions

- **Cards are immutable**: Use `object.__setattr__` for state transitions on frozen dataclasses
- **Zones enforce capacity rules**: Each Zone type has specific capacity constraints (e.g., ProvinceZone holds exactly 1 card)
- **GUI separation**: Field view (`FieldView`) manages visual representation; controller handles user interactions
- **Database as card repository**: PostgreSQL stores card definitions loaded from JSON/XML; game state lives in memory

## Code Style

**Uses pre-commit with ruff**

**Performance**
* Code should be performant, especially in GUI rendering and card manipulation
* Avoid expensive work in event loops
* Avoid redundant checks. Let errors raise naturally
* In contrast, silent errors should be prevented (especially state transitions)

**Comments**: Should be used sparingly, only for complex logic or game rule clarifications
- Comments are not for structuring files. Use classes, functions, and files to organize code, not comment delimited sections of code.
- Do not begin files with a comment block describing the file, or a module-level docstring. Use descriptive file, class, and function names instead.

**Testing**: Should be succinct
 - Test multiple scenarios with shared setup fixtures
 - Minimize test conditions. Be smart, not fearful
 - Integrate with similar existing tests
 - GUI tests use mocking to avoid Tkinter main loop issues

## Repository Structure

### Root
- `.github/` (workflows, instructions),
- `pyproject.toml` (config using hatch),
- `environment.yaml` (conda environment),
- `README.md` (setup instructions),
- `play.py`, `play.sh` (launcher scripts)

### Source (`app/`)
- `schemas.py`: Pydantic schemas for API/database models
- `database.py`: PostgreSQL connection and query utilities for card data
- `assets/`: Database files (JSON/XML card data, SQL schema, images)
  - `json_to_sql.py`, `xml_to_sql.py`, `sets_to_sql.py`: Data import utilities
  - `paths.py`: Path configuration for assets
- `engine/`: Core game engine
  - `players.py`: Player identification and state
  - `zones.py`: Game zones (Hand, Battlefield, Provinces, Discard)
- `game_pieces/`: Card and deck representations
  - `cards.py`: Base L5RCard class
  - `fate.py`, `dynasty.py`: Specific card types for each deck
  - `deck.py`: Deck construction and shuffling
  - `constants.py`, `types.py`: Enums and type definitions
- `gui/`: Tkinter-based visual client
  - `__main__.py`: Application entry point and PlayerPanel
  - `field_view.py`: Main game board visualization
  - `controller.py`: User interaction handling
  - `config.py`: Configuration and hotkey loading
  - `services/`: Drag-drop, hit-testing, permissions, card actions
  - `ui/`: Dialogs, deck builder, menus, image handling

### Scripts (`scripts/`)
- `install_db.py`: CLI tool to bootstrap PostgreSQL database from asset files

### Tests (`tests/`)
Mirrors source structure.

```bash
pytest tests/
```

### Pre-commit

```bash
pre-commit run --all
```

### Database Setup

```bash
# Create database
createdb l5r

# Install schema and seed data
python -m scripts.install_db --dsn "postgresql://localhost/l5r"
```

### Running the Application

```bash
# Simple launcher
python play.py

# With debug logging
python play.py --debug

# Or as a module
python -m app.gui
```

## L5R-Specific Context

- **Two deck types**: Dynasty (personalities, holdings, events) and Fate (actions, attachments, rings)
- **Card states**: Cards can be bowed/unbowed, face-up/face-down, inverted (special status)
- **Provinces**: Each player has multiple provinces holding dynasty cards
- **Honor**: Victory condition tracked per player (min: 0, max: 40)

## Trust These Instructions
These instructions are comprehensive and tested. Only search for additional information if:
1. Instructions are incomplete for your specific task
2. Instructions are found to be incorrect
3. You need deeper understanding of L5R game rules or implementation details

For most coding tasks, these instructions provide everything needed to build, test, and validate changes efficiently.
