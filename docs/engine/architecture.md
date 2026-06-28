# Rules Engine — Architecture (draft for review)

Companion to `docs/rules-skeleton.md` (what the rules *are*). This doc proposes *how the engine is
built*: the data model, the code organization, and the key design decisions. Decisions marked
**⚖️ SIGN-OFF** are forks where I want your call before we commit — the rest follows from them.

An earlier `yasuki_core/engine/game.py` was a throwaway **spike** (since removed); it only confirmed
that a `GameState` + a "pending decision" slot feels right. This doc is the design we build to.

---

## 1. Goals & constraints

- **Rules-driven, not a sandbox.** The engine owns the game; the client renders state and answers
  questions. (The existing `table.py` / `apply_intent` manual sandbox stays as a *debug/override*
  path, not the play path.)
- **Deterministic & replayable.** Same setup + same seeds + same decisions ⇒ same game. Enables
  save/load, undo, and reproducible tests. (Extends the existing `action_log.py` + `replay()`.)
- **Data-driven where it counts.** Card rules as data, so the future campaign rule-benders (dueling
  fads, tax policy → gold pooling) can mutate rules without rewriting the engine.
- **Incremental.** Playable at every step (Step 0 → 1 → 2 …), growing the ability vocabulary
  card-by-card rather than implementing all of L5R at once.
- **Reuse the core.** `TableState`, zones, `L5RCard`, `setup_seat`, `redact()` already exist and are
  good; build *on* them.

## 2. Key decisions (ADRs)

### KD1 — Mutable `GameState`, driven by a logged decision stream *(proposed, low-risk)*
`GameState` is mutable and **composes** `TableState` (keeps the shared sandbox model uncontaminated).
The engine's inputs are: the initial setup record, RNG seeds, and an ordered **log of player
decisions**. Determinism comes from seeded RNG; **replay re-executes** the engine feeding the logged
decisions (we do *not* serialize live engine internals). This extends the existing
`InitialRecord`/`ActionLog`/`replay()` pattern — the log's entries gain a `Decision` variant.
*Alternative rejected:* event-sourced/immutable reduce — heavier, and the codebase is already
mutable-state-with-log.

### KD2 — ✅ DECIDED — Abilities are **data (a small DSL) + an escape hatch**
A card ability is structured data, not bespoke code:
```
Ability(timing=Designator, keywords=[...], cost=[CostNode...], effect=[EffectNode...])
```
where cost/effect nodes are a closed, growing vocabulary of typed primitives the engine interprets —
`Bow(self)`, `PayGold(n)`, `ProduceGold(n)`, `Draw(n)`, `ModForce(target, n)`, `Destroy(target)`, …
For the long tail of weird cards, an **imperative escape hatch**: a Python callable registered by card
id. We grow the vocabulary one card at a time.
- *Backed by prior art (see Appendix):* MTG Arena (generic core + data rules + a text→data parser,
  ~80% auto), Forge (a `.txt` DSL covers ~95%; the hard minority drop to Java), Hearthstone
  (selector/action DSL), and LoR (per-card scripting because cards break rules) all converge on
  **declarative core + code escape hatch**. XMage (pure per-card code) proves all-code works but needs
  a developer per card.
- *Lessons folded in:* (1) design the DSL **and** the code escape hatch as one system with a clean
  seam from day one; (2) the hard part is **continuous/ongoing effects** (L5R's modifiers / bonuses /
  min-max / continuous traits) — model them as a **recomputed layer system, never bake stat values**
  (XMage does this; baking is the classic bug source); (3) keep code-backed effects **small and
  composable** — Forge's `CardFactory` ballooned to ~40k lines, a god-object to avoid.

### KD3 — ✅ DECIDED — Decisions via **request/response + a decision log** (not block-and-ask, not coroutines)
The engine runs until it needs player input, then records a typed **`DecisionRequest`** (who must
decide, the legal options, a resume cursor) on `GameState` and returns; the answerer submits a
**`DecisionResponse`**; the engine resumes. The **append-only decision log is the save format, the
replay format, and the netcode** (deterministic lockstep) — one mechanism, many payoffs.
- *Backed by prior art (see Appendix):* MTG Arena and Hearthstone both pause via an explicit
  server→client options/decision request and wait for the answer; the control-flow literature
  (event-sourcing, deterministic lockstep) independently lands on "state as plain data + input log."
- *Explicitly NOT block-and-ask:* XMage/Forge call a synchronous `player.choose(...)` that **blocks a
  game thread**. Clean for a thick desktop client, but thread-per-game and hostile to a web/async
  runtime, and not serializable mid-decision. Multiple sources flagged this as the one place the mature
  OSS engines are weakest and a new design should improve. We don't copy it.
- *Coroutines deferred, not adopted:* a suspended coroutine is opaque runtime state that breaks
  save-anywhere/replay. We may later add coroutines purely as **authoring sugar that compiles down to
  emitting the same `DecisionRequest`s** — but the log, not the coroutine, stays the source of truth.
- *Unified answerer:* one `Agent` interface answers requests — `human_ui`, `ai`, `network_peer`,
  `test` — so AI and online play are "just another answerer," nothing in the engine changes.
- *Determinism guard:* a CI test replays a logged game and asserts an identical final-state hash —
  one test covering determinism, save/load, and netcode at once. Hygiene we mostly already have:
  integers (L5R is all-integer), one seeded serializable RNG, canonical ordering of simultaneous
  triggers (the skeleton's timing tiers; cf. Hearthstone's immutable-queue model).

### KD4 — Engine↔client is three channels *(proposed)*
1. **Projection** — a per-seat *redacted* view of `GameState` (reuse/extend `redaction.py`); the GUI
   is a pure function of it.
2. **DecisionRequest / Response** — the engine asks, the seat answers. ~80% of play.
3. **Legal-action query** — "what can this seat do right now," powering the rules-driven card menu and
   target highlighting.
A thin façade (`engine session`) exposes `project(seat)`, `legal_actions(seat)`, `submit(response)`.

### KD5 — Engine owns its own low-level mutations *(proposed)*
The engine moves cards via internal operations (move/bow/produce/…), **not** the player-facing manual
`Intent`s. It may share small helpers with `table.py` (e.g. a move-card primitive) but the manual
intent path and the rules path stay distinct. Sandbox = debug; rules = play.

### KD6 — Stat-derived abilities are generic; printed abilities are authored *(proposed)*
A Holding/Stronghold with a Gold Production stat gets its `Bow: Produce N gold` ability **generically
from the stat** — no per-card data. The DSL/registry is only for *printed* abilities. (So Step 1 is a
generic stat behavior, not 40 hand-authored cards.)

## 3. Data model

```
GameState
├─ table: TableState              # zones, decks, cards, positions (existing)
├─ turn: int                      # increments each player-turn
├─ active: PlayerId
├─ phase: Phase                   # ACTION | ATTACK | DYNASTY (+ segments later)
├─ first_player: PlayerId
├─ gold: dict[PlayerId, int]      # transient pool, cleared on phase change
├─ favor_holder: PlayerId | None
├─ once_per: set[...]             # per-turn/per-game usage flags (Inheritance, etc.)
├─ stack: list[WorkItem]          # action sequence + queued triggers (grows in later steps)
├─ pending: DecisionRequest | None
└─ rng / seeds                    # seeded, for deterministic shuffles & replay

Decision types (closed union, grows):
  DiscardToHandSize(seat, count)
  ChoosePayment(seat, amount, sources)        # Step 2
  ChooseTarget(seat, candidates, ...)         # later
  OrderTriggers(seat, items)                  # later

Ability (data):
  Ability(timing, keywords, cost: list[CostNode], effect: list[EffectNode])
  CostNode:   Bow(who) | PayGold(n) | DiscardCard(...) | ...
  EffectNode: ProduceGold(n) | Draw(n) | BringIntoPlay(...) | ModStat(...) | Destroy(...) | ...
AbilitySource: card.id  →  [Ability...]   (registry; plus stat-derived defaults)
```

Card identity & states stay as today (`L5RCard`: bowed/face_up/owner/…; in-place mutation). Win-state
is derived, not stored: a checker runs at the trigger points from the skeleton (§1 of rules-skeleton).

## 4. Control flow

- **Turn loop / flow** — start-of-turn (straighten, reveal provinces) → Action → Attack → Dynasty →
  end-of-turn (fate draw, discard-to-hand-size) → next turn. Win-checks at the skeleton's trigger
  points.
- **Action round (priority)** — act-or-pass rotates in turn order; all-pass ends the round. Round type
  fixes which designators are legal and who acts first (rules-skeleton §8).
- **Action sequence** — Announce → Pay costs → Choose targets → Interrupts → Resolve → Response →
  Discard, modeled as `WorkItem`s on `stack`. Each step may emit a `DecisionRequest`.
- **Triggers** — detected after state changes, queued, ordered by the timing-conflict tiers
  (delay/negate → substitute → others), resolved off the stack.

(Steps 0–2 exercise only the turn loop, a trivial action round, gold production, and Recruit — the
stack/triggers grow later.)

## 5. Code organization

```
yasuki_core/engine/
  table.py            # EXISTING manual sandbox (TableState, apply_intent) — keep, untouched
  setup.py            # EXISTING deck deal — reuse; add game start
  redaction.py        # EXISTING — extend to project GameState per seat
  action_log.py       # EXISTING — extend log entries with Decision; replay re-runs the engine
  rules/              # NEW: the rules engine
    state.py          #   GameState, Phase/Segment, gold pool, once-per flags
    flow.py           #   turn loop, phases, start/end-of-turn, action rounds (priority)
    actions.py        #   action sequence (A–F + Response), announce/pay/target/resolve
    decisions.py      #   DecisionRequest/Response types
    rules.py          #   win/loss checks, hand size, legality helpers
    triggers.py       #   (later) trigger detection + timing-conflict ordering
    abilities/
      model.py        #   Ability, CostNode, EffectNode dataclasses (the DSL vocabulary)
      handlers.py     #   interpreters for each cost/effect node
      registry.py     #   card_id → abilities; stat-derived defaults (KD6)
  session.py          # NEW façade: project(seat) / legal_actions(seat) / submit(response)
```
The GUI (`yasuki_gui`) talks only to `engine/session.py` for play; it keeps the manual `apply_intent`
path for the debug sandbox. `yasuki_web` is unaffected.

## 6. Reusing yasuki_core's log / replay / redaction (the foundation)

The manual sandbox already ships an event-sourcing-lite stack in `engine/action_log.py` and
`engine/redaction.py`. Assessment: most of it **is** the rules engine's foundation; exactly one piece
needs generalizing.

**Reuse wholesale:**
- **Serialization** (`_encode_value`/`_decode_value`, `_encode_card`/`_decode_card`, the enum/card
  registries, zone/deck-key codecs, `action_log_to_dict`/`from_dict`) — the "state is JSON-ready plain
  data" machinery; handles enums, `Path`, tuples, frozensets, card subclasses. Reused verbatim. (Likely
  lift into a small shared `serialization.py` used by both the manual log and the game log.)
- **`InitialRecord` + `build_initial_state`** — the start-snapshot + rebuild pattern (event sourcing's
  "initial state"), already capturing seats, decklists, zones, battlefield, positions, and **named
  setup seeds**.
- **Append-only tape + replay-by-fold** (`ActionLog`, `replay()`) — an ordered tape folded onto a fresh
  initial state, with non-state entries (chat/session) interleaved and skipped. This *is* the
  decision-log model the research endorsed.
- **Seeded-RNG capture** (`LogEntry.rng_seed`, `setup_seeds`) — deterministic shuffles already
  recorded; the determinism precondition is met.
- **`FlushSink` / `flush`** — a ready persistence seam (no concrete sink yet) for a DB/object store.
- **`redact()`** — per-viewer projection hiding the opponent's hand / face-down cards / deck contents;
  reused to project `GameState.table`. The rules fields (phase, turn, active, gold counts) are public;
  `pending` is shown only to the seat that must answer it.

**Generalize (the one real change):**
- The tape's state-changing entry is currently a manual **`Intent`** (`LogEntry.intent`), folded
  through `apply_intent`. The rules engine's tape is player **`Decision`s** (answers to
  `DecisionRequest`s), and its replay must **re-run the engine** (advance phases, resolve abilities),
  feeding each logged decision at the matching request — not call `apply_intent`. So: keep the pattern
  and serialization; add a `Decision` entry variant and a **rules replay driver**. The manual
  `ActionLog`/`apply_intent` path stays intact for the sandbox and web.
- Start record: prefer recording **resolved decklists + first player + setup seeds** and letting replay
  run `setup_seat`, over snapshotting the post-deal table — smaller, and it exercises setup in replay.
  (`InitialRecord` already holds decklists + seeds, so this is a small adaptation.)

**Forward path it unlocks (not v0):** the engine can emit **`Event` deltas** (the type already exists)
as a causality-tagged stream to the client — Hearthstone's "blocks of tag-changes" model — giving
animation, spectating, and reconnect for free later.

Bottom line: the rules engine is **not** a from-scratch persistence/replay build. It extends a
foundation we already have — swap the entry payload from manual intents to engine decisions, add a
replay driver — which directly answers "can it be the foundation for a fuller system?": yes.

## 7. Build sequence (high level — detail once the model's signed off)

0. **Engine scaffold** — `rules/state.py` + `flow.py` + `decisions.py` + `session.py`; fold the spike
   into them.
1. **Step 0** — empty playable turn: phase loop, fate draw, discard decision, phase-bar UI.
2. **Step 1** — gold: gold pool in `GameState`, the stat-derived `Bow: Produce N` ability (KD6),
   `legal_actions` surfaces it, GUI gold-pool counter clearing on phase change.
3. **Step 2** — buy Holdings: a Recruit action + `ChoosePayment` decision + Holdings as gold sources;
   GUI pay prompt.
4. **Beyond** — personalities/HR, attack & battle resolution, the printed-ability DSL, triggers/stack,
   the full decision/targeting system, win checks.

## 8. Decisions (resolved)

- **KD1** ✅ mutable `GameState` composing `TableState`, driven by a logged decision stream.
- **KD2** ✅ data-first ability DSL + Python escape hatch; layer system for continuous effects.
- **KD3** ✅ request/response + decision log; not block-and-ask, coroutines deferred; one `Agent`
  interface answers requests; determinism/replay CI test.
- **KD4** ✅ three-channel engine↔client (redacted projection, decision request/response, legal actions).
- **KD5** ✅ engine owns its low-level mutations; manual `apply_intent` stays as the debug sandbox.
- **KD6** ✅ stat-derived abilities are generic; only *printed* abilities are authored.
- **KD7** ✅ reuse `action_log`/`redaction` as the persistence/replay/projection foundation (§6).

Still to settle when we build: the exact `Decision`/`DecisionRequest` taxonomy. (Shared serialization
is now lifted into `serialization.py` + `snapshot.py`.)

### Decision lifecycle — the concrete contract (built)

Every decision flows the same way, so adding one is data, not new plumbing:

1. **Request carries its options.** A `DecisionRequest` (closed union; `DiscardToHandSize`, then
   `ChoosePayment`, `ChooseTarget`, …) holds `seat`, `candidates` (the legal option ids — KD3's
   "legal options"), and `accepts(response)` — structural validity *drawn from the candidates*.
   `flow` populates `candidates` when it emits the request onto `GameState.pending`.
2. **One submit, one log.** `EngineSession.submit(seat, DecisionResponse(choices))` validates (seat +
   `accepts`) and dispatches to a per-type apply-handler in `flow.submit`; the input is logged and
   replayable. This path is decision-type-agnostic.
3. **A uniform `Agent` answers (KD3).** Bots (`AutoAgent` now, real AI later, `test`) implement
   `decide(request, view) -> DecisionResponse` — `AutoAgent` is generic, returning the shortest
   prefix of `candidates` its `accepts` allows. The **human is the non-blocking GUI presenter**, not
   a `decide()` call.
4. **Generic GUI presenter.** `runner.pending` (any request) → the prompt box shows a description +
   a Confirm gated by `request.accepts(selection)` → the board enters selection over
   `request.candidates` (clicking a candidate toggles a selection border) → `runner.submit`. The
   only per-decision GUI code is one line mapping the request to its prompt text + button label.

So a new decision = a `DecisionRequest` subclass (candidates + `accepts`) + a `flow.submit` arm +
the one-line prompt label. No new submit, log, replay, selection, or agent code.

## Appendix — prior-art research (why)

Four web-research passes (MTG Arena/MTGO, Hearthstone/LoR, open-source Forge/XMage, and the general
control-flow literature) converged on the same architecture, which is what this doc adopts:
**server/engine-authoritative · plain-data game state · request/response for player input · an
append-only input log that doubles as save + replay + netcode · a declarative ability DSL with a code
escape hatch.** The clearest single dissent — XMage/Forge blocking a thread on `player.choose(...)` —
is the one pattern we deliberately reject (KD3).

Key sources: MTG Arena rules-engine blog (Werner, "On Whiteboards, Naps, and Living Breakthrough");
*Magic: The Gathering is Turing Complete* (arXiv 1904.09828 — why perfect resolution is undecidable, so
guard loops); Riot LoR engineering blog (IronPython per-card scripting); HearthSim docs (entity/tag
model, Options/SendOption, Advanced Rulebook sequencing); Forge card-scripting wiki & XMage source
(DSL-vs-code contrast); Martin Fowler / event-sourcing and deterministic-lockstep writeups. Full URLs
are in the session research notes.
