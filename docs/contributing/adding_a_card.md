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

Five events exist to react to: `EnteredPlay`, `Destroyed`, `CardDiscarded`, `CounterGained`, and
`TurnStarted`. If the moment your card cares about is not one of these, it needs a new event — see
[what the vocabulary cannot express](#what-the-vocabulary-cannot-express-yet).

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
    return 1 if is_clan(me, "Lion") else 0
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
event is about *your* card before doing anything. **Return, don't mutate**: the list of effects is the
whole output.

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


@choice_resolver("wheat_farm")
def _wheat_farm_grant(game: GameState, source_id: str, chosen: tuple[str, ...]) -> list[Effect]:
    return [AdjustCounter(card_id, WEALTH, 1) for card_id in chosen]
```

The resolver is registered under a string rather than passed as a function, so a paused game stays
replayable — a stored closure would not rebuild to an equal object. Return an empty candidate list
when there is nothing to target: an ability with no legal target is not offered.

### Sequencing: making a step wait

Effects returned inline run before the events already queued behind them. When a step must happen
*after* other cards have reacted to what just happened, defer it with `Then`:

```python
return [
    RecruitCard(target.id, renew="Farm" in target.keywords),
    Then((Choose(source.owner, (source.id,), 0, 1, "modest_farm_straighten", target.id),)),
]
```

That is Modest Farm: recruit a Holding out of sequence, and *then* — once the recruited card's own
enter-play trait has resolved — offer to sacrifice the Farm to straighten it. Without `Then`, the
sacrifice would be offered before the recruited card had finished entering play.

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

- **Anything targeting an opponent's cards.** Effects address a card id, but nothing models the
  permission question — whose cards may this touch?
- **More than one ability on a card.** The ability registries hold one entry per card id.
- **Abilities usable from hand or province.** Triggers collect from the battlefield only.
- **Attachments.** No attach/detach model; a card cannot modify another by being attached to it.
- **Combat.** No attack, assignment, or resolution machinery.
- **Modal effects** — "choose one" where the modes are different *kinds* of effect. `Choose` picks
  cards, not modes.
- **Suppression** — one card turning another's ability off.

This list is measured, not guessed: a survey of a single arc found 109 cards with attachments, 27
targeting an opponent's cards, and 20 modal. If your card needs one of these, the honest next step is
a design discussion, not a workaround.
