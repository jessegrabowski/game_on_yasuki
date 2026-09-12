# Adding a card

A card's behavior lives in one module per set, mirroring the card data: `src/yasuki_core/assets/database/sets/rise_of_jigoku.yaml` pairs with
`src/yasuki_core/engine/rules/cards/rise_of_jigoku.py`. A reprinted card is implemented **once**, in
the set that printed it first, and a test enforces that.

Cards never mutate the board. A card returns *effects*, and one boundary applies them. The full type
list is in [Card Vocabulary](../design/card_vocabulary.md); this page is about choosing among them.

## Which hook?

Read the card's text and find the shape:

| The card says | Hook | Example |
|---|---|---|
| Produces a variable amount of gold | `@gold_handler(id)` | {card}`Jade Works` |
| Costs less to bring into play, conditionally | `@recruit_discount(id)` | {card}`Colonial Farm` |
| "After X happens…" | `@on(Event, id)` | {card}`Rice Farm` |
| An activated ability with a cost | `register_ability(id, Ability(...))` | {card}`Millet Farm` |
| "Response: after X…" | `register_ability(id, Ability(timings=(ActionTiming.RESPONSE,), ...))` | {card}`Caravansary` |
| Buy an extra effect while recruiting | `register_invest(id, InvestAbility(...))` | {card}`Rebuilt Harbor` |
| Carries a keyword only sometimes | `@keyword_grant(id)` | {card}`Fortified Farmlands` |
| Gives the Personality it hangs on a stat | `@attachment_grant(id)` | {card}`Haramaki-do` |
| Limits what it will attach to | `@attach_restriction(id)` | {card}`Brothers in Arms` |
| Buys its Invest cheaper, conditionally | `@invest_discount(id)` | {card}`Moto Ikarichi, Bloodseeker` |
| Changes the strength of an attack | `@attack_strength_against(id)` | {card}`Aseth's Legion` |
| Changes a Province's strength | `@province_strength_grant(id)` | {card}`Defensive Memorial` |
| Puts itself into play as an Edict | `register_edict(id)` | {card}`Act With Authority` |
| An Event played from the Province it sits in | `register_event_entry(id)` | {card}`Shadow of the Dark God` |
| Raises its own Gold Production as it bows | `register_self_grant(id, n)`, or `@self_grant(id)` when the grant has a condition | {card}`Jade Mine`, {card}`Slave Pits` |
| Enters play unbowed where the rule says bowed | `register_enters_unbowed(id)` | {card}`Poorly Placed Garden` |
| "May remain bowed" | `register_may_remain_bowed(id)` | {card}`Culling Grounds` |
| Waives the bow cost of the Personality it hangs on | `register_bow_waiver(id)` | {card}`Shadowlands Ambassador` |
| Pays somebody's Imperial Favor cost | `@favor_payer(id)` | {card}`Manjodh` |
| "You have a +N Lobby Bonus" | `@lobby_bonus_grant(id)` | {card}`Shigekawa's Court` |
| Stops a player Lobbying at all | `@lobby_bar(id)` | {card}`Wasp Sensei` |
| "May not Lobby" | `register_may_not_lobby(id)` | {card}`Moto Chen` |

Nine events exist to react to: `EnteredPlay`, `Destroyed`, `Straightened`, `CardDiscarded`,
`CounterGained`, `Revealed`, `TurnStarted`, `ProducingGold` and `ProducedGold`. If the moment your
card cares about is not one of these, it needs a new event — see [what the vocabulary cannot
express](#what-the-vocabulary-cannot-express-yet).

The `id` is the card's database id, the same string as in the set YAML. A pre-commit hook rejects an
id no card has, and tells you the nearest real one.

## The escalation ladder

Four rungs, in order of what they cost you. Start at the top and only descend when the rung above
cannot say what the card does.

### Answer a number: the gold handlers

{card}`Colonial Farm` is *"enters play for 1 less Gold if you are a Lion Clan player"*. The condition is the
only thing specific to the card, so the whole implementation is the condition:

```python
@recruit_discount("colonial_farm")
def _colonial_farm_recruit_discount(card: L5RCard, game: GameState, seat: PlayerId) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if is_clan(game, seat, ruleset.LION) else 0
```

Every handler is handed the game and the seat it acts for, and asks the narrow question it needs.
The shared predicates live in the `board/` package: `is_clan` in `board/clans.py`, and
`seat_controls_printed`, `seat_stronghold`, `cards_in_play`, `cards_named` and `went_second` in
`board/seats.py`. Look there before writing a predicate, since most clan and keyword questions
already have one.

### Return effects: reacting to an event

Rice Farm gains a Wealth token each turn, to a maximum of four. Existing effect (`AdjustCounter`),
existing event (`TurnStarted`), so only the condition is new:

```python
@on(TurnStarted, "rice_farm")
def _rice_farm_turn_started(ctx: TriggerContext) -> list[Effect]:
    """After your turn begins, give this Holding a +1GP Wealth token (max four)."""
    if ctx.card.owner is not ctx.event.seat or at_cap(ctx.card, WEALTH, 4):
        return []
    return [AdjustCounter(ctx.card.id, WEALTH, 1)]
```

Two things to copy. **Guard first**: a trigger fires for every copy of the card in play, so check the
event is about *your* card before doing anything. Which check depends on the event — Rice Farm
asks whose turn started, while a card reacting to its own arrival compares ids, since `EnteredPlay`
reaches every copy in play and not only the one that entered:

```python
    if ctx.event.card_id != ctx.card.id:
        return []
```

**Return, don't mutate**: the list of effects is the whole output.

### A choice: pausing for the player

{card}`Wheat Farm` lets its controller give up to two other Farms a token. The trigger cannot know what they
will pick, so it returns a `Choose` — an interrupting effect. The cascade pauses, the seat answers,
and a resolver turns the answer into effects:

```python
@on(EnteredPlay, "wheat_farm")
def _wheat_farm_entered_play(ctx: TriggerContext) -> list[Effect]:
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(...)          # the legal targets
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm", prompt="Give a Wealth token to other Farms you control")
def _resolve_wheat_farm(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]
```

The resolver is registered under a string rather than passed as a function, so a paused game stays
replayable — a stored closure would not rebuild to an equal object. Return an empty candidate list
when there is nothing to target: an ability with no legal target is not offered.

Register the `prompt` alongside it. Without one the seat is asked "Choose up to 2 card(s)", which
says how many cards to click and nothing about what for. Keep the wording free of counts — the same
choice can offer one target or two.

**A choice between modes** rather than between cards is `AskOption`, answered by a `ChooseOption`
decision. {card}`Honor Your Oaths` prints three modes with a different effect chain behind each, and the
resolver branches on the option the seat picked. Reach for it when the card says "choose one" and
the things being chosen are not cards.

### A division: how many go where

{card}`Suiteiru no Oni` creates a Follower per point of the Chi of the Personality he destroys, and attaches
them "to one or more of your Personalities". The seat picks the bearers *and* how many each takes, so
a `Choose` — which reads its answer as a set — cannot say it. `AskDistribution` can: the answer names
a card once per creation it takes, and the resolver reads that tally.

```python
return [
    Destroy(target.id, source.owner),
    AskDistribution(source.owner, bearers, podlings, "suiteiru_no_oni", source.id),
]


@choice_resolver(
    "suiteiru_no_oni", prompt="Attach the Oni Followers to one or more of your Personalities"
)
def _resolve_suiteiru_no_oni(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    return [
        *(CreateToken(SUITEIRUS_PODLING, seat, source_id, attach_to=bearer) for bearer in chosen),
        GainHonor(seat, -len(chosen)),
    ]
```

Everything offered is placed — the seat divides the creations rather than declining any — so raise
the question only when there is both something to divide and somewhere to put it. The client draws a
count and a pair of arrows on each card the seat picks, and the prompt counts down as they are
placed; the registered wording carries no number for that reason.

### Sequencing: making a step wait

Effects returned inline run before the events already queued behind them. When a step must happen
*after* other cards have reacted to what just happened, defer it with `Then`:

```python
question = f"Destroy {source.name} to straighten {target.name}?"
return [
    RecruitCard(target.id, renew=keywords.FARM in target.keywords),
    Then(
        (
            Ask(
                source.owner,
                question,
                "modest_farm_straighten",
                subjects=(source.id,),
                source_id=target.id,
            ),
        )
    ),
]
```

That is Modest Farm: recruit a Holding out of sequence, and *then* — once the recruited card's own
enter-play trait has resolved — offer to sacrifice the Farm to straighten it. Without `Then`, the
sacrifice would be offered before the recruited card had finished entering play.

## Cards that attach

A Follower, Item or Spell acts through the Personality carrying it, and the two bow costs are not
the same: the `:bow:` icon bows the attachment, and only the written-out "Bow this Shugenja" reaches
the Personality. [Cards that attach](attachments.md) works through that, `@attachment_grant` and
`@attach_restriction`. [Units and attachments](../design/systems/units-and-attachments.md) is the
system behind it.

An ability printed `Battle:` carries `ActionTiming.BATTLE` and is an ordinary `register_ability`
call. `battle_designators`, `targets_any_location` and `located_at` decide what it may reach, and
[Cards that act in a battle](battle_cards.md) covers them.

## Cards that create

A created card is stamped from a token template, so its stats, keywords and art come off a print
rather than the creation site. `CreateToken` carries all of it, including attaching the new card
and fixing a template's variable stat.
[Cards that create cards](creating_cards.md) works through it, and
[Effects](../design/systems/effects.md) is where the effect sits in the vocabulary.

## Cards that watch their own bow

`register_may_remain_bowed` takes a card out of the turn-start straighten, and a `Straightened`
trigger is how it pays for that when it does stand up. Culling Grounds is both, and
[Cards that create cards](creating_cards.md) works through it alongside the creation it protects.

## Cards that attack

`RangedAttack`, `MeleeAttack` and `Fear` are effects taking a strength, a target and a cause, and
`attack_targets` is the target predicate every attack card wants. A card that changes an attack's
strength registers `@attack_strength_against` instead of an ability.
[Cards that act in a battle](battle_cards.md) works through both, and
[Battle](../design/systems/battle.md) is the system behind them.

## Cards that print two abilities

A card may register as many abilities as it prints. Each one after the first needs a `key`, because
the action names the ability it takes by key and the designator often cannot tell them apart — both
of Incendiary Archers' abilities are Battle:

```python
register_ability(
    "incendiary_archers",
    Ability(
        timings=(ActionTiming.BATTLE,),
        label=f"Battle, Bow: Ranged {INCENDIARY_ARCHERS_RANGED} Attack",
        cost=bow_cost,
        targets=attack_targets,
        effects=_incendiary_archers_ranged_effects,
        key="ranged",
    ),
)
```

`register_ability` refuses a second *unkeyed* ability and a repeated key, so an ambiguous
registration cannot exist. A card printing one ability needs no key and none of the existing
registrations carries one.

Both halves are offered independently, and each pays its own cost — so a card whose first ability
bows it can still take a second that does not, once the opportunity comes back around. Name the
three handlers `_<card id>_<key>_<role>`, since two `effects` functions on one card would otherwise
collide.

## Where the code goes

Find the set that printed the card first, and open the module of the same name as its YAML file. Add
the card in id order under a header:

```python
# --- Rice Farm ---
```

Everything the card does goes in that one block: its triggers, its target predicates, its effects
helper, its registration. A pre-commit hook asserts the ordering, the one-header-per-card rule, and
that the header names the card the block registers, on the modules your commit touches.

Name every function in the block for the card and the job it does — `_<card id>_<role>`, where the
role is one of `cost`, `targets`, `effects`, an entry point of a registry (`gold`, `invest`,
`keywords`, `recruit_discount`, `invest_discount`, `attachment_grant`, `attach_restriction`,
`attack_strength`, `province_strength`, `lobby_bonus`, `lobby_bar`, `favor_payer`), or the event a
trigger answers (`entered_play`,
`destroyed`, `straightened`, `turn_started`, `counter_gained`, `card_discarded`, `producing_gold`,
`produced_gold`, `entered_play_or_destroyed`). A card printing several abilities qualifies the role
with that ability's key — `_incendiary_archers_fear_effects` — since one name per role would collide
between them, and the key has to be one the module really registers. A choice resolver is named for
the choice instead, `_resolve_<the string it is registered under>`. Helpers the block calls but
never registers only need the card's id in front. The point is grep: a card's whole implementation answers a search
for its id, and every handler of a kind answers a search for its role. A test enforces it, and
`ROLES` in `hooks/card_layout.py` is where a genuinely new role gets added.

A brand new set module needs a line in `cards/__init__.py`; a test will tell you if you forget.

## Checking your work

```bash
pixi run test          # the suite
pre-commit run --all   # includes the card-id check
```

Write the test with the card. The suite is how a mass refactor knows it did not drop your
registration — every implemented card is covered, and that is not an accident.

## What the vocabulary cannot express yet

Knowing a card is out of reach before you start is worth more than any amount of reference. Each of
these needs a core extension, not just a card module:

- **A general rule about whose cards you may touch.** A card *can* target an opponent's — Touch of
  Death destroys any bowed Personality with Chi no higher than its caster's — but each handler
  filters by owner itself. There is no permission model to ask, so a card whose restriction is a
  rulebook one rather than its own text has nowhere to read it from.
- **Suppression** — one card turning another's ability off.
- **Negating or cancelling** anything. No effect of either kind exists, so a card that stops an
  action, an ability or an effect from resolving has nothing to return.
- **A battle designator that depends on the board.** `battle_designators` is a static `frozenset` on
  the `Ability`, so "Absent while you hold the Imperial Favor" cannot be one ability. Split it into
  two abilities gated separately.
- **Detaching.** `AttachCard` puts an attachment on and no effect takes one off. An attachment
  leaves only by the state rule that discards one left with no Personality.
- **Interrupt abilities.** The designator exists and no Action Round grants it, so an ability
  carrying it is never offered. Response, the other half of the pair, is served by the Response
  Step. Combining is an Interrupt ability too (CR, Combining), so it waits on the same layer.
- **Duels.** No focus, no resolution.

This list is measured, not guessed: a survey of a single arc found 27 cards targeting an opponent's
cards. If your card needs one of these, the honest next step is a design discussion, not a
workaround.
