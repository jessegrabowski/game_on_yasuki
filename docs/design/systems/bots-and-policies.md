# Bots and policies

Adding a card has a tail most authors do not expect. The bots cannot read what a card does, so a
new activated ability is invisible to them until someone says what it is worth.

## Why a card can be invisible

`ABILITY_HINTS` is a per-card registry like any other, and the comment above it states the rule:

```python
# The activated abilities a policy has an economic model for, by printed id. An ability absent here
# is never activated: a policy cannot read what a card does, and guessing at an unmodelled one would
# spend a bow on an effect it has no way to value.
ABILITY_HINTS: HandlerRegistry[AbilityHint] = HandlerRegistry(
    "ability hints", "already has an ability hint"
)
```

An ability with no hint is never taken by a bot, which is the safe behavior when a policy has no
way to price it. A card is playable by a human the moment its handler lands, and it joins the bots'
repertoire when someone writes the hint.

## What a hint says

```python
worth_activating: Callable[[GameView, L5RCard], bool]
best_target: Callable[[GameView, ChooseAbilityTarget], str] | None = None
optional_cost_answers: Mapping[str, Callable[[GameView, ChooseCards], bool]] = field(
    default_factory=dict
)
```

`worth_activating` is required and answers whether taking the ability now is worth its cost.
`best_target` picks among candidates, and a hint without one takes the first candidate the way a
generic agent would. `optional_cost_answers` answers an optional cost the resolution offers.

The last is keyed by choice resolver rather than by card. The request carries the card the cost is
paid *for*, not the card charging it.

## Two registrations that raise

{func}`~.register_ability_hint` refuses a second hint for one card, and it refuses a hint claiming
a resolver another card already answers:

```python
for resolver in hint.optional_cost_answers:
    if resolver in _OPTIONAL_COST_ANSWERS:
        raise ValueError(f"{resolver} already has an optional cost answer")
_record_hint(printed_id, hint)
_OPTIONAL_COST_ANSWERS.update(hint.optional_cost_answers)
```

A resolver names one card's cost, so two hints claiming it is a typo in one of them. The check runs
before either half is recorded, so a refused registration leaves nothing behind.

A hint reads a {class}`~.GameView` rather than a {class}`~.GameState`. A policy sees what a player
sees.

## Where a card plugs in

Nowhere, until you want the bots to use it. A hint is optional, it lives in `bots/hints.py` rather
than with the card, and the card works without one.
