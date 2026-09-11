# Package Boundaries

The dependency direction is one-way at every level. `yasuki_core` imports neither front-end. The
board substrate under `engine/` does not read `engine/rules/`, and the rules layer does not import
`bots/`. Nothing in `rules/vocabulary/` imports anything above it, and `ruleset.py` reaches no
further than that vocabulary. `search/` turns query text into SQL without touching `database.py`.
`stats/` never reads `gold/`. Neither `accounts/` nor `sim/` is imported by anything shipped.
A package `__init__` re-exports nothing, so a symbol has one import path and a module can be
moved by rewriting it; `yasuki_core`, `search/` and `cards/` are the three that do, the last
aggregating its set modules on purpose.

Nothing under `engine/` or `game_pieces/` imports `psycopg`. The engine is a pure in-memory state
machine, and the one path from it to Postgres runs through `game_setup.py`, above both trees. This
one is worth knowing about when you review a diff: `psycopg` imports fine with no database, so a
query on the board-mutation path raises nothing until something tries to connect.

None of that is enforced, and it should not be. Violating any of it leaves a worse dependency graph
and breaks nothing at runtime, which makes it a code review's job. A `grep` answers each one in a
second when the question comes up. A `TID251` ban in ruff was tried for the `psycopg` rule and
dropped: ruff's per-file-ignores only subtract, so scoping it to two trees meant banning the import
repo-wide and then excusing the seven paths that legitimately connect, which inverts the rule into
an allowlist that rots.

## What the suite does check

Two properties, both in `tests/yasuki_core/test_fresh_import.py`, and both about runtime behavior
rather than the shape of the source.

Importing `engine/rules/` in a fresh interpreter must not raise. A cycle that the suite's own
import order papers over is an `ImportError` for the first consumer that reaches the modules
differently.

Importing the engine must register the cards. The registries fill from importing the set modules
for their side effects, and any test that touches a card leaves those modules in `sys.modules` for
the rest of the session. Registration that works under the suite and not standalone leaves every
per-card rule inert.

## Which seams are extraction-ready

Three packages could be spun out without untangling anything first.

`sim/` is the Monte Carlo harness, 601 lines. It imports the engine and the bots, and no shipped
module imports it. It is the clearest candidate.

`accounts/` is 1,233 lines across 11 modules with its own connection pool and its own database. No
module in it imports `engine/` or `game_pieces/`, and no GUI module imports it.

`bots/` is 1,313 lines and has six importers, all of which take `Agent`, `Policy` or `Controls`.
The dependency on the engine is real and one-way.

A fourth is worth stating with its evidence rather than asserting. `yasuki_web` imports nothing
under `engine/rules/`, so the whole rules layer is GUI-only, which makes moving it out from under
`engine/` arguable on the same grounds as the three above. It is also 8,000-odd lines and the
substrate it sits on is shared with the manual intent surface that both front-ends drive, so the
move is larger than the others and the evidence here is a starting point rather than a conclusion.
