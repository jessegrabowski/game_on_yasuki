---
name: game-pieces
description: >
  Use this whenever you touch the card model or game objects in src/yasuki_core/game_pieces — the
  L5RCard dataclass and its Dynasty/Fate subclasses, card identity (id vs printed_id), the
  flag/visibility state (bowed, face_up, inverted, counters…), Deck, the Counter model, or the factory
  that builds live cards from database rows — and read it before adding a field or subclass rather than
  guessing the hierarchy, since these are frozen dataclasses with non-obvious mutation rules. Covers the
  immutable pieces the whole engine manipulates. How pieces are held and mutated on the board is the
  engine-state skill; how their data is stored is the card-data skill.
---

# Game pieces (the card model)

## Where it lives

`src/yasuki_core/game_pieces/`:

- `cards.py` — `L5RCard` (the base card); `constants.py` — the `Side` enum (FATE/DYNASTY/STRONGHOLD)
- `prints.py` — `CardPrint` and every typed print beneath it: `DynastyPrint` (Personality,
  Holding, Event, Region, Celestial), `FatePrint` (Action, Attachment, Ring, Ancestor), and
  `StrongholdPrint` / `SenseiPrint` / `WindPrint`
- `deck.py` — `Deck`; `counters.py` — `Counter`; `factory.py` — build live cards from DB records

## What it does

`L5RCard` is a `frozen`, slotted dataclass. **Identity is split**: `id` is the per-instance id (`"P1-0"`),
`printed_id` is the stable database slug shared by every copy and printing — effect handlers key off
`printed_id`. It carries `side`, `clan`/`clans`, `keywords`, `traits`, `card_type`, `creates` (token
ids), and the mutable-looking flag/visibility state (`bowed`, `face_up`, `inverted`, `shown`, `peekers`,
`showing_back`/`back`/`back_card_id`, `is_token`, `note`, `counters`). Because it's frozen, mutators use
`object.__setattr__` (`bow`, `flip`, `adjust_counter`, `add_peeker`…); `active_face` returns the
presented face.

Subclasses add the stats: `DynastyCard` → Personality/Holding/Event/Region/Celestial (`gold_cost`,
`force`, `chi`, `honor_requirement`, `gold_production`); `FateCard` → Action/Attachment/Ring/Ancestor
(`focus`, `timings`, `attachment_type`, `element`). `Deck[CardT]` is a LIFO (top = end) with
`draw`/`peek`/`shuffle(seed)`. `Counter` is a frozen *kind* of marker with per-count stat deltas, loaded
from `counters.yaml` into `ALL_COUNTERS`. `factory.resolve_decklist` turns a parsed decklist + DB
records into a `ResolvedDeck` (one instance per physical copy, cross-seat-unique `id`);
`build_token_card`/`build_token_templates` build spawnable tokens.

## How it fits the big picture

These are the immutable atoms the engine moves around. `factory` builds them from database rows (see the
`card-data` skill) during setup; the `TableState` substrate holds them in zones and decks, and both the
manual and rules surfaces mutate them via `ops` / their transition methods (see the `engine-state` and
`rules-engine` skills). Never assign a card attribute directly — go through the transition methods so
changes stay explicit.

Full narrative: `docs/contributing/what_a_card_is.md` separates the card record, the print and the
in-play `L5RCard`, and explains why eighteen data types resolve to twelve print classes.
`docs/design/database.md` is the underlying data. `docs/design/engine.md` is still a stub.
