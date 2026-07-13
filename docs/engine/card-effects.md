# Card Effects — Per-Card Handlers (variable gold production first)

Companion to `docs/engine/architecture.md`. This doc records *how a card's behaviour is
computed* when it isn't a plain printed number — starting with variable gold production, the first
case to need it.

It **refines KD2** of the architecture doc. KD2 proposed abilities as *data (a small DSL) + an
escape hatch*. Building it out, the DSL loses: it fights you the moment a card's logic doesn't fit
its vocabulary, and the gold-production cases alone already span counters, game-state predicates,
history, and player choice. We go the other way — **per-card handlers in code** — because code lets
us factor the common logic into shared helpers, which is exactly what the DSL was trying (and
failing) to give us. The card DB stays the data source of truth for *printed* stats/text; handlers
are the engine's *behavioural* layer keyed off card identity.

---

## 1. The problem

Most holdings produce a fixed integer. A minority don't. Enumerating the **136 Shattered-Empire-arc
holdings**: 98 are plain, and ~24 have genuinely variable *own* gold production (the heuristic
flagged 38, but ~14 are false positives — plain GP plus an unrelated ability that merely mentions
gold — or GP-*givers* whose own production is plain). The ~24 split into tiers by **how much
machinery they need**, which drives the phasing:

| Tier | Mechanic | ~Count | Examples | Status |
|------|----------|--------|----------|--------|
| **A. Wealth tokens** | effective GP = printed + `+1GP` counters on the card | ~10 | Caravansary, Rice Farm, Sapphire Mine | **state + math done** — `counters` on the card, wealth summed by the dispatcher; placing-triggers deferred |
| **B. State-conditional** | base + bonus while a predicate over live state *or the target* holds | ~9 | Ancestral Estate, Dockside Market, Tanuki Band, Jade Works | **done** (Ancestral/Dockside/Jade Works) |
| **C. Modal** | a genuine player-chosen bow-mode | 0–1 | Basecamp (re-verify) | likely a phantom — see note below |
| **D. Pre-bow pump** | player may boost before bowing, at a cost | 2 | Outlying Farms, Zokujin Burrows | deferred — player choice |
| **E. Dynamic −1GP** | engine bows/straightens with a temp penalty | 2 | House of High Waters, Depths of the Shinomen | deferred — phase triggers |

Plus ~6 **GP-givers** (Millet/Wheat Farm, Ichiba, Otokoshi) whose own GP is plain but whose job is
handing `+1GP` tokens to *other* holdings — also deferred (they need a "give token" action and the
Tier-A model).

Many of these tiers (B's predicates over Favor/Wind/Compassion, the token triggers) are themselves
blocked on subsystems that don't exist yet. The two cards whose state exists *today* are **Ancestral
Estate** (compare stronghold GP — composes with the sensei GP fold) and **Dockside Market** (count
your Port/Market holdings). Those are Phase 1.

## 2. ✅ DECIDED — Per-card handlers, uniform signature

A card's variable behaviour is a **pure Python function registered against the card's identity**:

```python
@gold_handler("ancestral_estate")
def ancestral_estate(card, me, opponents, targets):
    outproduced = any(o.stronghold.gold_production > me.stronghold.gold_production for o in opponents)
    return card.gold_production + (1 if outproduced else 0)
```

**Uniform signature `(card, me, opponents, targets) -> int`.** Every handler takes the full payload
whether or not it uses all of it — the way pytensor node rewriters all take `(fgraph, node)`. The
dispatcher then calls them generically and there is never a "what does this one need?" question.
*Rejected: dependency-by-name dispatch* (pass only the params a handler declares) — more ergonomic
per handler, but the introspection turns into hell to debug and breaks consistency.

When a card eventually needs a dimension the signature lacks, it goes into the signature and **every
handler gets it** — the accepted, mechanical tax, exactly like widening a rewrite protocol.

### Dispatch

```python
def effective_gold_production(card, me, opponents, targets):
    handler = GOLD_HANDLERS.get(card.printed_id)
    if handler is None:
        return card.gold_production          # the 98 plain holdings cost nothing
    return handler(card, me, opponents, targets)
```

The four current read-sites (`gold_producers`, `produce_gold`, `ChoosePayment.produced`,
`session._recruits`) route through this.

The **same payload serves other effect hooks**, not just production. Moto Traders ("enters for 1
less Gold if you control another Merchant Caravan") is a *recruit-cost* reducer — `recruit_cost`
becomes a `@cost_handler` with the identical `(card, me, opponents, targets)` signature. This is a
general card-effect resolution payload, gold production is just its first consumer.

## 3. ⚠️ Prerequisite — stable card identity

A live `L5RCard` carries `id` (per-instance, `"P1-3"`), `name`, and `back_card_id` — but **no stable
printed identity** to key a handler on. Keying on `name` is fragile (extended titles, experienced
versions). The DB record already has `card_id` (the slug `"ancestral_estate"`, one per card across
printings); the factory just doesn't thread it onto the card.

**First task:** add `printed_id: str | None` to `L5RCard`; `factory._construct_face` sets it from
`record["card_id"]`. Fabricated demo cards and spawned tokens leave it `None` → no handler → plain
behaviour, which is correct. This is the key every per-card handler (gold now, abilities later)
dispatches on.

## 4. ✅ DECIDED — What a handler can read: decomposed, perspective-relative views

No single god context. The payload decomposes so the signature itself documents what's available:

- **`card`** — the producing card (printed base, later its counters).
- **`me`** — a read-only `PlayerState` for the controller: `.stronghold`, `.holdings`, `.in_play`,
  `.gold`, `.honor`, helpers like `.controls("Port")` / `.controls("Merchant Caravan", other_than=card)`.
- **`opponents`** — list of the other players' `PlayerState`s.
- **`targets`** — the cards being paid for or acted on, as a tuple (a recruit payment is a 1-tuple;
  empty outside a targeted context; multi-target abilities carry several). Only the modal tier reads
  it today, but it's included from the start for signature uniformity.

**The battlefield is *not* a separate param.** Every in-play card has a controller, so the
battlefield decomposes per-player into `me.in_play` / `opponent.in_play`. Moto Traders' "another
Merchant Caravan you control" is `me.controls(...)`. A flat `battlefield` param would just force
`[c for c in battlefield if c.owner is me and ...]` back into every handler — the owner-filtering
boilerplate the views exist to delete. Cross-player aggregates are a one-line helper over the views.

`me` / `opponents` are **read-only projections of existing state**, not new authority.

### Perspective-relative, not absolute

`me` / `opponents` rather than `player1` / `player2`: handlers read "an opponent out-produces me"
with no seat-branching, and the same handler works for either seat because the views are built from
the producer's perspective.

## 5. ✅ DECIDED — History via a semantic event log, never the input tape

Some cards ask whether something *happened*: Fine Silk Merchant ("+1GP for each action you resolved
this turn from your Retainers, max +2"), Teardrop Island ("if you brought a Port into play this
turn"), every "this turn" / "once per turn" clause.

A **fixed tally** (`me.this_turn.retainer_actions`) is rejected: it forces the *engine* to
pre-enumerate every query a future card might invent. You can't.

The **raw input tape** (`GameLog` of Acts/Answers/Cancels) is also rejected: too low — a card would
re-interpret what a Recruit input *did*, coupling itself to the serialization format.

The middle, and the decision: the engine emits a **derived, turn-scoped semantic event log** —
typed domain events as state changes resolve (`ActionResolved(source, controller, turn)`,
`CardEnteredPlay(card, controller, turn)`, `HonorLost(player, n)`, …). The card brings **its own
predicate**:

```python
@gold_handler("fine_silk_merchant")
def fine_silk_merchant(card, me, opponents, targets):
    n = me.this_turn.count(lambda e: e.kind is ACTION_RESOLVED and e.source.has_keyword("Retainer"))
    return card.gold_production + min(2, n)
```

So `me.this_turn` is a **filterable event stream**, not a fixed-schema tally — the generality the
tape promised, minus the rawness. Why it's the right altitude, not a compromise:

1. **General without pre-enumeration** — emitting "an action resolved, source=X" needs no foresight
   about who'll ask; the predicate lives on the card.
2. **Substrate we need anyway** — L5R is wall-to-wall `Response:` / `After:` / `Before:`; the
   trigger/reaction system *is* an event bus. History-queries and reactions read one stream.
3. **Lighter than the input tape** — events are turn-scoped (discard at turn end, keep a few durable
   "this game" facts), semantic (no re-interpretation), and **derived** — rebuilt by replaying
   resolution, never serialized. Replay stays deterministic; the save format doesn't bloat.

This is a **later tier** — the event bus is real infrastructure that lands with triggers, not with
Ancestral Estate (which reads only live state).

## 6. Constraints

- **Handlers are pure functions of their args** — no RNG, no mutation. A turn-tally / event log is
  already part of deterministic game state, so reading it is replay-safe. Player *choices* (the
  modal tier) go through the **decision log**, never inside a handler.
- **The global axes** that genuinely don't decompose per-player — province count, current phase,
  contested rings/favor — become new uniform-signature params (or a `global`/`table` view) when the
  first card needs them. The battlefield is *not* one of these; it's player-owned all the way down.

## 7. Phase 1 build order

Scope: **Tier B only** — stateless state-conditional gold production. No new card state, no decision
protocol change, no GUI change.

1. `printed_id` on `L5RCard` + factory plumbing (§3).
2. `PlayerState` view (`me` / `opponents`) over existing state; the helper library (`controls`,
   `stronghold`, …).
3. `GOLD_HANDLERS` registry + `@gold_handler` decorator + `effective_gold_production`; route the four
   read-sites through it.
4. First handlers: `ancestral_estate`, then `dockside_market` (proves the helpers generalize past a
   one-off). Unit-tested — predicate pure, effective-GP pure, replay-safe.

Deferred, in rough order of likely demand: Tier A (Wealth-token counters + the stat-change model),
the event bus + Tier-B history cards (Fine Silk Merchant), Tier C modal (decision protocol + GUI +
non-pooling excess), Tiers D/E.

## 8. Open forks (not blocking Phase 1)

- **Wealth-counter universality.** Audited across the DB: every Shattered-Empire-legal grant is
  templated "+1GP Wealth token" and no SE-legal holding hosts one without the bonus, so the
  dispatcher adds the wealth sum unconditionally — there is no per-card opt-out. The known future
  exception is pre-SE bank-style cards (Moneylender: tokens cash out by *removal*, no passive GP);
  older "Produce N plus 1 Gold for each Wealth token" texts (Estate Halls, The Mikado) are just old
  wording of the universal rule. If those arcs come into scope, the dispatcher needs an opt-out or
  handler-owned counter math.

- **Handler module layout.** Where `GOLD_HANDLERS` / helpers live, and how handlers organise as the
  pool grows (by set? by effect hook? one registry vs per-hook registries). Start with one module;
  split when it chafes.
- **Event vocabulary.** The set of emitted event kinds + fields — grows with triggers, designed when
  the event bus lands, not now.
- **"Modal" was a stale-text phantom.** Jade Works looked modal in the **oracle text** the DB still
  carries ("Produce 5 Gold, which can only pay for a single Jade card"). The **current errata'd
  card** reads "This Holding has +2GP when paying for a single Jade card only" — a plain conditional
  bonus (Tier B), no mode choice, no non-pooling restriction; the +2 pools like any gold. So it's
  just a `targets`-aware handler (`+2` when a target is Jade). No `ChoosePayment` mode options, no
  `accepts` non-pooling, no GUI mode-pick were needed. Before treating any card as truly modal,
  check its *current* text, not the DB's oracle text — Basecamp likely reframes the same way, which
  may leave genuine player-chosen modes empty. (Follow-up: the DB card text itself is stale oracle
  text; refreshing it to current errata is a separate data task.)
