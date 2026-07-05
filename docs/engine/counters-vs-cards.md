# Counters vs Cards — a shared vocabulary for two branches

Two feature branches are touching "token"-shaped things at once, and L5R overloads the word
"token" across mechanically-different concepts. This note fixes the vocabulary so the branches
compose additively at merge instead of colliding on one over-broad "card" model.

- **This branch** (card-effects / variable gold) needs **counters** — scalar state *on* a host card
  (Wealth `+1GP` tokens, Sincerity, Honor, Void tokens).
- **The other branch** (tokens / proxy cards) needs **spawned cards** — independently-existing cards
  an effect or the sandbox creates.

These are not two flavours of one thing. Modelling them as one ("everything is a card") is a
category error that produces phantom objects — a "card" with no force, no zone, that exists only to
mean *+1 to a stat*.

## The three things "token" means in L5R

| Concept | What it is | Card? | Owner |
|---------|-----------|-------|-------|
| **Counter / marker** | a named tally *on* a host card — Wealth (`+1GP`), Sincerity, Honor, Void | **No** | this branch |
| **Attachment** | a real card (Follower / Item / Spell) attached to a host, modifying it | Yes (already) | neither — exists |
| **Spawned / proxy card** | an effect- or sandbox-created card (a made Personality, Ashigaru, a proxy) | **Yes** | other branch |

## Counter — the contract (this branch owns)

A counter is **scalar host state, not a game object.**

- Has no force/chi, no zone, no position, no owner of its own.
- Cannot be targeted, moved, bowed, or destroyed independently — abilities target the *host*.
- Dies with its host; leaves play when the host does.
- N copies collapse to an integer. "Give this Holding a +1GP Wealth token" is `+1` to a tally.
- Lives as data *on* `L5RCard` — planned `counters: dict[str, int]` (serialises through the generic
  field codec for free, exactly like `printed_id`).
- Consumed by effect handlers: `effective_gold_production` reads `printed + counters.get("wealth",
  0)`. Because ~10 Tier-A holdings share that identical math, the wealth sum belongs in the
  dispatcher **fallback**, not in 10 per-card handlers — a card needs a handler only for logic
  *beyond* the generic counter sum.
- The triggers that *place* counters (Responses, Invests, turn-start) are separable ability work,
  deferred; manual add/remove in the sandbox for now. The counter *state + its stat math* is the
  Tier-A deliverable.

## Spawned card — the contract (other branch owns)

A spawned card **is a full `L5RCard`** that simply wasn't drawn from a deck. This already exists:

- `L5RCard.is_token: bool` marks it; `SpawnCard`/`RemoveCard` intents and `ops.spawn_token` create
  and destroy it; the web board draws it with the token back and keys it by a `spawn-`-style id.
- It has real card identity: id, name, side, position, can be moved / bowed / removed / targeted.

So `token` / `is_token` already means **spawned card** in the codebase — the other branch's sense.
Keep it that way.

## The rule

1. **`token` / `is_token` / `SpawnCard` = spawned card.** Never overload them to carry stat-state.
2. **`counter` (or `marker`) = scalar host state.** A distinct field of a distinct type; never an
   `L5RCard`, never spawned, never `is_token`.
3. A Wealth token is a **counter**, not a token-card — even though the game text says "token."
4. The category error to reject in review: representing a counter as a tiny spawned/proxy card, or
   adding stat-state onto the `is_token` path. If a "token" has force, a zone, or can be targeted,
   it's a card; if it's a number that modifies its host, it's a counter.

## Merge surface

With the names apart the branches are additive: the other branch grows `SpawnCard`/proxy lifecycle
on the card model; this branch adds `counters` to `L5RCard` and reads them in the effect dispatcher.
The only shared file is `cards.py` (one new field), and the only shared discipline is not
conflating the two concepts — which this note exists to prevent.
