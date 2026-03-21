# Game on, Yasuki! Copilot Instructions

## Overview

**Game on, Yasuki!**: Online client for playing classic Legend of the Five Rings (L5R) card game. Python 3.12+, uses Tkinter (GUI), FastAPI (multiplayer), PostgreSQL (card database), Pydantic (schemas), PIL/Pillow (image handling), pytest.

For setup, running, Docker, and contribution workflows see `docs/`.

## Design Principles

- **Three-package architecture**: `yasuki_core` (engine + data), `yasuki_web` (FastAPI API), `yasuki_gui` (Tkinter desktop client)
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
- **Dependency direction**: `yasuki_core ← yasuki_web`, `yasuki_core ← yasuki_gui`. No dependency between web and gui.
- **Assets split**: Bundled images (defaults, card backs) live in `yasuki_core/assets/images/`. Card set images (~8 GB) live outside the package in `sets/` (override with `YASUKI_SETS_DIR` env var).

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

## Repository Layout

```
pyproject.toml              # Build config (hatch + pixi)
play.py                     # GUI launcher
sets/                       # Card set images (gitignored, ~8 GB)
docs/                       # All documentation
audits/                     # Architecture decision records

src/
├── yasuki_core/            # Engine, cards, DB, search, install, assets
├── yasuki_web/             # FastAPI API, schemas, deck builder SPA
└── yasuki_gui/             # Tkinter GUI, controller, services, visuals

tests/
├── yasuki_core/
├── yasuki_web/
└── yasuki_gui/
```

Full structure details: `docs/development.md`

## L5R-Specific Context

- **Two deck types**: Dynasty (personalities, holdings, events) and Fate (actions, attachments, rings)
- **Card states**: Cards can be bowed/unbowed, face-up/face-down, inverted (special status)
- **Provinces**: Each player has multiple provinces holding dynasty cards
- **Honor**: Victory condition tracked per player (min: 0, max: 40)

## Quick Reference

```bash
pixi run play              # Launch GUI
pixi run api               # Start API server
pixi run test              # Python tests
pixi run test-js           # JS deck builder tests
pixi run install-db        # Seed database
pre-commit run --all       # Lint
```

## Trust These Instructions
These instructions are comprehensive and tested. Only search for additional information if:
1. Instructions are incomplete for your specific task
2. Instructions are found to be incorrect
3. You need deeper understanding of L5R game rules or implementation details

For operational details (setup, Docker, contributing), see `docs/`.
