# Counters vs Cards — reconciling the token PR with the game engine

Two efforts touch "token"-shaped things, and L5R overloads "token" across mechanically-different
concepts. This note fixes the vocabulary and the division of labour so they compose additively.

- **`feature/token-creation`** is a **bridge from the tabletop-simulator model** (full-freedom, every
  object is a draggable card/proxy) **toward the rules-driven engine**. It adds token *creation*:
  a `Token` card type, a `creates` / `card_creates` relation, `SpawnCard` / `ops.spawn_token`, and a
  synthetic `tokens.yaml` set (~1900 entries).
- **This branch** (card-effects) is **100% engine-driven**, so it can leapfrog part of that bridge:
  the pieces the TTS model represents as cards *only because the sim has no rules* become first-class
  engine state here.

## The three things "token" means

| Concept | What it is | Engine representation | Where it lives |
|---------|-----------|----------------------|----------------|
| **Counter / marker** | a named tally *on* a host — Wealth (`+1GP`), Sincerity, Honor, `+1Chi` | a scalar (`counters: dict[str,int]` on the host) | this branch |
| **Attachment** | a real card (Follower / Item / Spell) attached to a host | already an `L5RCard` | exists |
| **Created / spawned card** | an effect- or sandbox-created card (a made Personality, Ashigaru) | a full `L5RCard` via `SpawnCard` | token PR |

## What the token PR actually models (read, not assumed)

- `L5RCard` gains `card_type` and `creates: tuple[str, ...]` (the `card_creates` links, resolved at
  deck load); a per-card **Create** menu spawns a token id; `ops.spawn_token` puts a full card on the
  battlefield. This part is real and directly reusable for genuine card-tokens.
- The `tokens.yaml` set holds **both** genuine card-tokens (`Personality Token 0/2/2`, Ashigaru —
  force/chi, first-class) **and** proxy-markers (`token_wealth`, `token_plus1gp` — `types: [Token]`,
  `is_proxy: true`, an inert `gold_production: 1`, text "*attach for its modifier; not deckable*").
- **Attachment / host-modifier resolution is not implemented.** The only new engine op is
  `spawn_token`; nothing reads an attached marker to change a host's stat. So a spawned Wealth proxy
  is a *visual sandbox piece with no effect* — a faithful port of the TTS crutch, no more.

That inert-proxy representation is exactly the conflation to leave behind: modelling pure host state
as a card produces a phantom object — a "card" with no zone, no target, no effect, that exists only
to *mean* "+1 to a stat".

## The leapfrog

- **Proxy-markers → counters.** We do **not** port `token_wealth` / `token_plus1gp` as cards. A
  marker is a scalar on the host (`counters["wealth"]`), authoritative and replay-hashed, read by the
  effect dispatcher: `effective_gold_production = printed + counters.get("wealth", 0)`. Because ~10
  Tier-A holdings share that identical math, the wealth sum lives in the **dispatcher fallback**, not
  in per-card handlers — a card needs a handler only for logic beyond the generic counter sum.
- **Created-card tokens → keep `SpawnCard`.** A made Personality / Ashigaru genuinely *is* a card;
  the engine needs the spawn path for card effects that create cards. Reuse the PR's work here as-is.
- **The migration tell for a `creates:` link.** A link pointing at a *proxy-marker* id ("give this
  Holding a Wealth token") becomes a **counter-grant ability** on the engine side (`counters[...] +=
  1`); a link pointing at a *genuine card* stays a spawn. No spawn-then-attach for markers, and so no
  "spawn-proxy → counter" bridge to build — the counter is the representation from the start.

## The rule

1. **`token` / `is_token` / `SpawnCard` = a created card.** Never overload them to carry stat-state.
2. **`counter` (or `marker`) = scalar host state.** A distinct field of a distinct type; never an
   `L5RCard`, never spawned, never `is_token`.
3. A Wealth token is a **counter**, not a token-card — even though the game text and the TTS bridge
   both say "token".
4. Review red-flag: if a "token" has force, a zone, or can be targeted, it's a **card**; if it's a
   number that modifies its host, it's a **counter**. Reject representing a counter as a proxy/spawned
   card, or hanging stat-state off the `is_token` path.

## Merge surface

Additive. The token PR grows the create/spawn model on the card layer (`card_type`, `creates`,
`spawn_token`); this branch adds `counters` to `L5RCard` and reads it in the effect dispatcher. The
only shared file is `cards.py` (each side adds fields), and the only shared discipline is not
re-conflating the two concepts — which this note exists to prevent. When the branches meet, the
proxy-marker entries in `tokens.yaml` are retired in favour of counters; the created-card entries and
the whole spawn path stay.
