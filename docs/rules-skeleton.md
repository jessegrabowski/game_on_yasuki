# L5R Rules Skeleton (engine spec, v0)

Distilled from the **Twenty Festivals Comprehensive Rules** (AEG) with the **Onyx Edition & Shattered
Empire Rules Datasheet** overlaid. This is the structural model the rules engine must implement — the
*skeleton*, not every edge rule; consult the CR for detail. Onyx/ShE deltas are marked **[Onyx]**.

Scope note: v0 targets the current rules as printed. Rule-bending campaign mechanics (dueling fads,
tax policy → gold pooling, etc.) are deliberately out of scope but motivate keeping rules data-driven.

---

## 1. Object of the game & win/loss

Each player wins by one of four paths; the game ends the instant a player wins (2-player: a player's
loss makes the other the winner of the matching type). Checked continuously unless noted:

| Path | Condition | When checked |
| --- | --- | --- |
| **Military** | a player has **0 provinces** → they lose | immediately |
| **Honor** | a player **starts their turn at Family Honor ≥ 40** → they win | start of turn |
| **Dishonor** | a player's Family Honor **≤ −20 at the end of their turn** → they lose | end of turn |
| **Enlightenment** | control **5 Rings of 5 different elements** (Air/Earth/Fire/Water/Void) → win | immediately |
| **Special** | card-granted win/loss conditions (named per card) | per card |

## 2. Players & resources

- **Family Honor** — integer, may go negative; seeded from the Stronghold's Starting Honor (modified
  by Sensei). Gains/losses are instantaneous and atomic; a 0-point gain/loss doesn't count as one.
- **Gold pool** — transient currency (§7). Produced by bowing the Stronghold / Gold-producing
  Holdings; the pool **empties at the end of each phase**.
- **Maximum hand size** — default **8**, enforced at end of turn.
- **Imperial Favor** — a single shared token; some actions require discarding it. **[Onyx]** Lobby /
  Favor rulebook actions; a player with a Wind in play may not take rulebook Favor actions.
- **Clan Alignment** — from the Stronghold; gates Recruit cost and "same/different clan" effects.
  **[Onyx]** legal clans: Crab, Crane, Dragon, Lion, Mantis, Phoenix, Scorpion, Spider, Unicorn,
  Akasha; multi-mon Personalities belong to each; no legal alignment ⇒ Unaligned.

## 3. Card model

Two play decks + starting cards. **Deck construction:** 40+ Dynasty, 40+ Fate, 1 Stronghold, 0–1
Sensei (and **[Onyx]** 0–1 Wind, which starts in play); ≤1 of a Unique title, ≤3 of a non-Unique
title (different Experienced levels count separately).

| Type | Deck | Key stats |
| --- | --- | --- |
| **Stronghold** | starting (in play) | Province Strength, Gold Production, Starting Family Honor |
| **Sensei** | starting (in play, optional) | modifiers to the Stronghold's stats |
| **Wind** **[Onyx]** | starting (in play, optional) | — |
| **Holding** | Dynasty | Gold Cost, Gold Production (optional); enters play **bowed** |
| **Personality** | Dynasty | Force, Chi, Honor Requirement, Gold Cost, Personal Honor |
| **Event** | Dynasty | abilities usable while face-up in a province |
| **Strategy** | Fate | Focus Value; played from hand then discarded |
| **Ring** | Fate | Focus Value; element keyword (Enlightenment) |
| **Attachment** (Follower / Item / Spell) | Fate | Gold Cost, Focus Value; Follower has Force; Item has Force/Chi modifiers; Spell attaches only to Shugenja |

**Stats:** computed as (apply all modifiers/bonuses/penalties) → then min/max; basic minimum 0 (only
Honor Requirement, Family Honor, and signed modifiers go negative). `*` = variable stat (printed 0).

**Key stat rules:**
- **Chi Death** — a Personality at **Chi 0 is destroyed immediately**; only a *continuous* effect can
  prevent it (single-shot "don't destroy" effects can't).
- **Honor Requirement** — cannot Recruit a Personality whose HR > your Family Honor. If a player loses
  Honor due to anything other than their own cards, they ignore HR for their own clan for the rest of
  the game.

**Abilities:** structured as `[ability keywords] Designator: [costs] effects`. Only the **bow icon**
and **Gold icon** are costs; everything after the colon is effects. Traits are passive/triggered text;
keywords are tags (boldface = rules-bearing). See §10 for the keyword taxonomy.

## 4. Card states (flags)

`in_play` (derived from area), `bowed`/unbowed, `honorable`/`dishonorable` (Personalities; dishonorable
caps Personal Honor at 0; rulebook honor loss = printed PH when a dishonorable Personality is
destroyed), `face_up`/`face_down`, `location` (home or a battlefield), plus **control** (who may use
it; can change) vs **ownership** (whose deck it came from; never changes). A destroyed Personality in
the discard is **dead** (honorable/dishonorable dead tracked); other cards are merely discarded.
Attachments form a **unit** with their Personality.

## 5. Zones / areas

Per-player unless noted; "in play" vs "out of play" comes from the area.

| Zone | In play | Ordered | Visibility |
| --- | --- | --- | --- |
| Dynasty deck / Fate deck | out | yes | hidden (count & identity hidden even from owner) |
| Provinces (**4**) | out | row L→R | dynasty card face-down→face-up |
| Dynasty / Fate discard | out | no | public |
| Dead (subset of dynasty discard) | out | no | public |
| Hand | out | rearrangeable | hidden to others; owner sees own |
| Home | **in** | — | public; default place cards enter play; a *location* |
| Battlefield(s) + Side (Attacker/Defender) | **in** | adjacency | public; temporary; *locations* during battle |
| Focusing area | out | — | own face-down visible to owner only (duels) |
| Entering-play / Resolution areas | out | — | face-up, transient |
| Under another card / Outside the game | out | — | per rules |

**Visibility invariant** (drives client redaction): everyone always knows face-up card identities,
the full game state of effects/stats, each player's Family Honor, and hand *counts* — but **not** deck
sizes, face-down identities, or opponents' hidden cards. **[Onyx]** default province creation goes to
the left of the leftmost; loss without a target hits the rightmost.

## 6. Turn structure

Setup → repeated turns until someone wins. Turn order proceeds to the left; the active player acts
first in most rounds.

**Start of game:** (A) reveal Strongholds/Sensei, set starting Honor; (B) highest Honor goes first
(ties random) — **[Onyx]** first player uses the **Sun** side, others the **Moon** side (Moon side
grants the once-per-game **Inheritance Rule**); (C) shuffle; (D) make 4 provinces, fill L→R from the
dynasty deck; (E) all draw 5 Fate cards; (F) starting player takes the first turn. *No mulligan* — the
first-turn **Cycle** action is the only opening fix.

**The turn — three phases, then the fate draw:**

1. **Action Phase**
   - Start: active player **straightens all** bowed cards, then **turns own province cards face-up**.
   - Action round: active player may take **Limited** + **Open** actions; opponent may take **Open**
     actions. Player abilities here include Cycle (first turn), Equip, Lobby, rulebook Favor.
2. **Attack Phase** (optional)
   - **Declaration:** declarer = Attacker, opponent = Defender; a battlefield is created at **each of
     the Defender's provinces**.
   - **Maneuvers:** Attacker assigns unbowed Personalities (from home) to battlefields, then Defender
     does. A unit led by a bowed Personality can't be assigned.
   - **Fight Battles:** Attacker picks a battlefield; resolve a battle (§9); repeat until every
     battlefield has been fought once (exactly one battle each). Then battlefields cease; leftover
     attackers bow and return home.
3. **Dynasty Phase** — active player takes **Dynasty** actions:
   - **Recruit:** bring a face-up Personality/Holding from a province into play, paying its Gold Cost
     (+2 Gold if its clan ≠ yours); Personality needs Honor ≥ its HR; Holdings enter bowed.
   - **Proclaim:** once/turn, when Recruiting your own-clan Personality from a province, add its
     Personal Honor to your Family Honor after it enters play.
   - **Dynasty Discard:** discard a face-up province card.
   - Leaving a province triggers its **refill** (face-down from the dynasty deck) once effects settle.
4. **Fate draw (end of turn):** draw 1 Fate card; discard down to max hand size. Then the next player.

## 7. Economy

Gold is produced by **bowing** the Stronghold or Gold-producing Holdings during a cost payment;
excess goes to the **Gold pool** for later costs **this phase**; the pool empties at end of phase.
A single Recruit/Equip payment covers both the action's cost and the brought-in card's Gold Cost.
**Restricted** ("single purpose") gold is tracked separately, never pools, and any excess vanishes
after that action's Pay-Costs step.

## 8. Action & timing model (the engine's core loop)

**Action round = priority loop:** the player with the opportunity takes an action or **passes**;
opportunity moves in turn order; when **all players pass consecutively, the round ends.** Round types
fix which action **designators** are legal and who goes first:

| Round | Legal actions | First |
| --- | --- | --- |
| Action Phase | active: Open+Limited; others: Open | active |
| Engage segment | Engage | Defender |
| Combat segment | Battle | Defender |
| Dynasty Phase | Dynasty | active |
| Interrupt step (within an action) | Interrupt | active |

**Action Sequence** (steps in order, taken by the acting player):
- **A. Announce** the action (show the card if it's a Strategy/Ring from hand).
- **B. Pay costs** (only bow + Gold icons are costs; produce/spend Gold here).
- **C. Choose targets** (non-delayed, non-optional, not chosen by another player).
- **D. Interrupts** — all players may play Interrupt actions to this action.
- **E. Resolve** — carry out effects in written order; targeting actually happens now; if a required
  target is missing, effects stop immediately.
- **E.5 Response step** **[Onyx]** — after resolution, before discard, all players may play **Response**
  actions (starting with the active player).
- **F. Discard** the card unless it's now in play.

**Effects** (anything that isn't a cost): durations are **instantaneous** (marked changes, never wear
off), **ongoing** (until end of current turn unless stated), or **continuous** (non-triggered traits,
on while in play). Resolve in written order.

**Triggers:** "if" triggers fire *after* the occurrence; "when" triggers fire between *before* and
*after* (mainly gold-on-payment, "would"-choice modifiers, continuous on/off). **Timing-conflict
order** when several trigger at once (active player breaks ties within a tier): **(A) delay/negate/
prevent → (B) substitute → (C) all other triggered effects.**

**Targeting:** the word "target" is required; targets chosen at step C, carried out at step E; legal
targets must be in play unless the ability implies otherwise.

## 9. Battle resolution

1. Each side totals **Army Force** = Force of all **unbowed** Personalities + Followers (Items modify
   their Personality's Force regardless of bow; **[Onyx]** Elite contributes while bowed, Conqueror
   doesn't bow from resolution). A side with no units has 0 Force.
2. **Higher Force wins.**
   - **Attacker wins:** destroy all defending units; if attacking Force **>** defending Force **+
     Province Strength**, also **destroy the province**.
   - **Defender wins:** destroy all attacking units.
   - **Tie** (both have units): mutual destruction. Tie at 0 with an empty side: no outcome.
3. **Honor:** the winner gains Honor = **2 × enemy cards destroyed by resolution** (both gain on a tie).
4. **After resolution:** attacking units bow and return home; on the last battle, defenders return
   home (no bow); discard Terrains; battlefield ceases.

**[Onyx] Raid battles:** an extra single-battlefield attack not at a province; its resolution doesn't
destroy defending armies or provinces; benefits only what cards specify.

## 10. Keyword / trait / designator taxonomy

The card-ability vocabulary the effect system must eventually express (mostly **[Onyx]**):

- **Designators** (when an action may be taken): Open, Limited, Engage, Battle, Dynasty, Interrupt,
  **Response**.
- **Ability keywords** (modify an action): Absent, Home, Remote, Tactical, Raid, Lobby, **Unstoppable**.
- **Boldface keywords** (rules-bearing): Cavalry, Conqueror, Courage, Destined, Duty, Elite,
  Expendable, Honesty, Honor, Kensai, Kharmic, Legacy, Naval, Renew, Reserve, Sincerity, Singular,
  Tactician, Fortification, Shugenja, Naval, Cavalry…
- **Traits** (rules-bearing, non-boldface): Compassion, Courtesy, Discipline, Honesty, Invest,
  Sincerity, Yu.
- **Iconized keywords:** elements (Air/Earth/Fire/Void/Water), Jade/Maho/Pearl/Thunder, Shadowlands;
  Fear / Melee / Ranged icons; the Favor icon.
- **Keyword inheritance:** an ability's keywords apply to its card; a card's keywords apply to its
  abilities.
- Terms: **Banish** = remove from game; **Edict** = a Strategy, max 1 in play.

---

## 11. What this means for the engine (design implications)

The current `yasuki_core.engine.table.TableState` + `apply_intent` is a **manual sandbox** — it has
zones, cards, and state-mutating intents, but no turn/phase/priority/effects. The rules engine adds a
layer on top:

- **GameState** = TableState + `active_player`, `phase`/`segment`, the priority/action-round state, a
  resolution **stack** (action sequence A–F incl. the Response step), and **pending decisions**.
- **Ability/Effect model** — a structured representation of `Designator: cost → effect`, with
  triggers, durations, and targeting. The hard, incremental part; implement card abilities over time,
  not all at once. (Card text → executable ability is a DSL problem, not NLP.)
- **Legal-action generator** — given GameState + seat, what actions/decisions are available now. Powers
  both the rules-driven context menu and target highlighting.
- **Decision protocol** — the engine pauses and asks the seat a typed question (target, cost, order,
  mulligan/keep, assign attackers); the client answers. This is ~80% of play.
- **Win/loss checker** — run at the trigger points in §1.
- **Redaction** — project GameState to one seat per §5 visibility (reuse `engine/redaction.py`).
- The existing manual `apply_intent` stays as a **debug/override mode**, not the play path.

### v0 milestone (a playable basic game)

Turn loop + the three phases, the action-round priority loop, gold/Recruit economy, attack + battle
resolution, the four win checks, and a **minimal ability framework** with a handful of hand-coded
cards — deferring the full ability DSL and most keyword interactions. Build the GUI (phase bar,
decision prompts, zone trays) against the engine's decision protocol from the start.

### v0 decisions (settled)

- **Format: Shattered Empire** (the Onyx/ShE datasheet is authoritative for clan list, keywords, etc.).
- **No opening-hand mulligan.** Opening-hand fixes are first-turn **Cycle** and the **Inheritance Rule**:
  the second player (Moon side) may, once per game, `Dynasty: turn the Stronghold over` (Moon→Sun) to
  give a target Holding +3 GP. (Sun = first player, one mon / black border; Moon = second player, two
  mons / white border, and only Moon has the Inheritance ability.)
- **Multiplayer rules ignored** (single-player vs AI; AI is secondary to the rules engine).
- **No dueling/focus in v0** — defer focus pools, strikes, the duel sequence.

### Build order (v0 increments)

- **Step 0 — Empty playable turn:** a phase bar the player advances; nothing else playable. Draw a
  fate card at end of turn, discard to hand size (first decision prompt), track turn number.
- **Step 1 — Static gold production:** a DSL for static Gold from the Stronghold; left-click → `Bow:
  Produce N gold`; a gold-pool counter (MTGO-style) that clears on phase change.
- **Step 2 — Buy Holdings:** left-click a Holding → `Pay N gold` prompt → pay from Stronghold / pool;
  Holdings produce Gold to buy more Holdings. Static production only.
