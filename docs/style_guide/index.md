# Style Guide

Conventions for contributing code to Game on, Yasuki! The authoritative, always-current source is
`.github/copilot-instructions.md` and the project's `CLAUDE.md`; this page collects the essentials.

```{note}
This page is an outline. The full write-up is still being written; the bullets below are the intended
sections.
```

## Principles

- **Self-documenting code.** Descriptive names over comments; comments explain *why*, never *what*.
- **Lean hot paths.** No redundant checks or work that can be hoisted out of a loop, especially in GUI
  rendering and card manipulation. Let errors raise rather than swallowing them.
- **Immutable game pieces.** Cards are frozen dataclasses with explicit state-transition methods.
- **One-way dependencies.** `yasuki_core ← yasuki_web`, `yasuki_core ← yasuki_gui`; web and gui never
  depend on each other.

## Planned Sections

- Docstring conventions (NumPy style, active voice, human-readable types).
- Comment restraint and what earns a comment.
- Testing philosophy (shared fixtures, succinct scenarios, fakes over mocks).
- Modern-Python idioms and typing expectations.
