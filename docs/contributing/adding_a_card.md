# Adding a Card

A card's behavior lives in one module per set, mirroring the card data: `src/yasuki_core/assets/database/sets/rise_of_jigoku.yaml` pairs with
`src/yasuki_core/engine/rules/cards/rise_of_jigoku.py`. A reprinted card is implemented **once**, in
the set that printed it first, and a test enforces that.

Cards never mutate the board. A card returns *effects*, and one boundary applies them. The full type
list is in [Card Vocabulary](../design/card_vocabulary.md); this page is about choosing among them.

## Which hook?

Read the card's text and find the shape:

| The card says | Hook | Example |
|---|---|---|
| Produces a variable amount of gold | `@gold_handler(id)` | Jade Works |
| Costs less to bring into play, conditionally | `@recruit_discount(id)` | Colonial Farm |
| "After X happens…" | `@on(Event, id)` | Rice Farm |
| An activated ability with a cost | `register_ability(id, Ability(...))` | Millet Farm |
| Buy an extra effect while recruiting | `register_invest(id, InvestAbility(...))` | Rebuilt Harbor |
| Carries a keyword only sometimes | `@keyword_grant(id)` | Fortified Farmlands |
| Gives the Personality it hangs on a stat | `@attachment_grant(id)` | Haramaki-do |
| Limits what it will attach to | `@attach_restriction(id)` | Brothers in Arms |

Six events exist to react to: `EnteredPlay`, `Destroyed`, `CardDiscarded`, `CounterGained`,
`Revealed`, and `TurnStarted`. If the moment your card cares about is not one of these, it needs a
new event — see [what the vocabulary cannot express](#what-the-vocabulary-cannot-express-yet).

The `id` is the card's database id, the same string as in the set YAML. A pre-commit hook rejects an
id no card has, and tells you the nearest real one.

## The escalation ladder

Four rungs, in order of what they cost you. Start at the top and only descend when the rung above
cannot say what the card does.

### Answer a number: the economy handlers

Colonial Farm is *"enters play for 1 less Gold if you are a Lion Clan player"*. The condition is the
only thing specific to the card, so the whole implementation is the condition:

```python
@recruit_discount("colonial_farm")
def _colonial_farm(card: L5RCard, me: PlayerState, opponents: tuple[PlayerState, ...]) -> int:
    """Enters play for 1 less Gold if you are a Lion Clan player."""
    return 1 if is_clan(me, ruleset.LION) else 0
```

`is_clan` is shared, in `economy.py`. Look there before writing a predicate — most clan and keyword
questions already have one.

### Return effects: reacting to an event

Rice Farm gains a Wealth token each turn, to a maximum of four. Existing effect (`AdjustCounter`),
existing event (`TurnStarted`), so only the condition is new:

```python
@on(TurnStarted, "rice_farm")
def _rice_farm(ctx: TriggerContext) -> list[Effect]:
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

Wheat Farm lets its controller give up to two other Farms a token. The trigger cannot know what they
will pick, so it returns a `Choose` — an interrupting effect. The cascade pauses, the seat answers,
and a resolver turns the answer into effects:

```python
@on(EnteredPlay, "wheat_farm")
def _wheat_farm(ctx: TriggerContext) -> list[Effect]:
    if ctx.event.card_id != ctx.card.id:
        return []
    others = tuple(...)          # the legal targets
    if not others:
        return []
    return [Choose(ctx.card.owner, others, 0, min(2, len(others)), "wheat_farm", ctx.card.id)]


@choice_resolver("wheat_farm", prompt="Give a Wealth token to other Farms you control")
def _wheat_farm_grant(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]
```

The resolver is registered under a string rather than passed as a function, so a paused game stays
replayable — a stored closure would not rebuild to an equal object. Return an empty candidate list
when there is nothing to target: an ability with no legal target is not offered.

Register the `prompt` alongside it. Without one the seat is asked "Choose up to 2 card(s)", which
says how many cards to click and nothing about what for. Keep the wording free of counts — the same
choice can offer one target or two.

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

A Follower, Item or Spell is not a fifth rung — Touch of Death is an activated ability like any
other, and Brothers in Arms is a trigger. What sets an attachment apart is that it acts *through*
the Personality carrying it, and three registries cover the ways it does.

**Reaching the Personality.** `attached_to(game, card)` returns it, or None when the card hangs on
nobody. Most often a cost needs it: an attachment's ability usually spends its Personality's bow
rather than its own.

```python
        cost=bow_parent_and_destroy,
```

Watch the two bow costs — they are different. The `:bow:` icon in an ability's cost line means bow
*the card the ability is on*, which is `bow_cost`. Only the written-out "Bow this Shugenja" reaches
the Personality. Every Shattered Empire card paying with its parent is a Spell using that wording.

**Giving the Personality a stat** it does not print. Haramaki-do prints +2F and reads "This
Personality has +1PH"; the printed half is a number on the card, the written half is a grant:

```python
@attachment_grant("haramaki_do")
def _haramaki_do(game: GameState, card: L5RCard, host: L5RCard) -> dict[Stat, int]:
    """This Personality has +1PH. The +2F is printed on the card and needs no handler."""
    return {Stat.PERSONAL_HONOR: 1}
```

**Limiting what it will hang on.** The rulebook's own restrictions — one Weapon, Two-Handed
exclusivity — live in `equip.py` as code. A restriction only one card states lives with that card:

```python
@attach_restriction("brothers_in_arms")
def _brothers_in_arms_attaches_only_to_a_samurai(
    game: GameState, personality: L5RCard, card: L5RCard
) -> bool:
    return keywords.SAMURAI in effective_keywords(game, personality)
```

Two things an attachment gets for free, so do not write handlers for them: a card leaving play takes
its attachments with it, and a state rule discards an attachment left with no Personality.

**Battle is still out of reach**, and for attachments that is most of the corpus — 1,284 of the
abilities printed on Follower, Item and Spell cards are Battle abilities. An attachment card whose
text begins "Battle:" cannot be implemented today no matter which rung it would otherwise sit on.

## Cards that create

Weapon Artist makes a sword out of nothing; Colonial Farm makes an Ashigaru; Mishime Sensei makes an
Oni. What they create is a card in its own right — the "Proxy" prints in the database, reached by
token card id — so its stats, keywords and art come off that print rather than being spelled out at
the creation site. The deck load resolves every token the deck's cards can create and parks the
templates on the table, which is why a card names one by id and nothing else:

```python
FINE_SWORD = "weapon_item_sword_plus2f_plus1c"
```

Creating is one effect, and creating-and-attaching is still one, because the created card has no id
until it exists:

```python
    return [CreateToken(FINE_SWORD, source.owner, source.id, attach_to=target.id)]
```

The third argument is the card doing the creating. It is remembered, so a card that speaks about
what it made — "if this Holding is ever unbowed, banish the Personality" — can ask for it later
rather than hunting the board for something that looks right.

**Attachment targets** are the catch. The rules that decide where an attachment may hang — one
Weapon per Personality, Two-Handed exclusivity — have to be answered before there is a card to ask
about, so `creation_targets` judges the template instead:

```python
    sword = game.table.creatable_tokens[FINE_SWORD]
    return [target.id for target in creation_targets(game, source.owner, sword)]
```

**A variable stat line** — "a Personality with Force equal to the target's Chi" — is printed on the
token as `*` and supplied by the card creating it. Pass the numbers it fixes and the created card
genuinely has them, rather than carrying a modifier over a printed zero:

```python
        CreateToken(
            MISHIMES_ONI,
            seat,
            sensei.id,
            stats=((Stat.FORCE, effective_chi(game, target)),),
            banish_at_turn_end=not destroyed,
        )
```

`banish_at_turn_end` is the other half of that card: a creation lent to its owner for one turn is
recorded as it is made, because by the time the turn ends there is nothing left to decide.

A created card is not a copy of a real one: it exists only in play, and destroying it, banishing it,
or destroying the Personality carrying it takes it off the table rather than into a pile. That is
handled for you.

A cost paid in Gold rather than a bow is an effect like any other, and raises the same payment a
Recruit does:

```python
    return [PayGold(source.owner, ASHIGARU_COST, source.name)]
```

## Cards that watch their own bow

Culling Grounds trades an Honor and a bow for a Personality, and keeps it only while the Holding
stays bowed. Two registrations carry that. The first is the printed "May remain bowed", which takes
the card out of the turn-start straighten — a flag, since the card grants the permission and says
nothing about when taking it is worth it:

```python
may_remain_bowed("culling_grounds")
```

The second is what happens when it does straighten. Straightening announces itself, whether the turn
start or an effect did it, so the drawback is an ordinary trigger:

```python
@on(Straightened, "culling_grounds")
def _culling_grounds_gives_up_its_servant(ctx: TriggerContext) -> list[Effect]:
    ...
    return [Banish(created) for created in ctx.game.creations_of(ctx.card.id)]
```

Its ability names no target at all. An ability still needs one to be offered, so it takes its own
card and hits it without asking:

```python
        targets=itself,
        all_targets=True,
```

## Where the code goes

Find the set that printed the card first, and open the module of the same name as its YAML file. Add
the card in id order under a header:

```python
# --- Rice Farm ---
```

Everything the card does goes in that one block: its triggers, its target predicates, its effects
helper, its registration. Tests assert the ordering, the one-header-per-card rule, and that the
header names the card the block registers.

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
- **More than one ability on a card.** The ability registries hold one entry per card id.
- **Abilities usable from hand.** An ability is offered from the battlefield or from a Province
  (`located_at`); a card in hand is out of reach.
- **Combat.** No attack, assignment, or resolution machinery.
- **Modal effects** — "choose one" where the modes are different *kinds* of effect. `Choose` picks
  cards, not modes.
- **Suppression** — one card turning another's ability off.

- **Interrupt and Response abilities.** Both designators exist and no Action Round grants either,
  so an ability carrying one is never offered. Response is a Shattered Empire addition, and the
  largest single gap in the vocabulary.

This list is measured, not guessed: a survey of a single arc found 27 cards targeting an opponent's
cards and 20 modal. If your card needs one of these, the honest next step is a design discussion,
not a workaround.
