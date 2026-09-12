# The Imperial Favor

The Favor is a thing one seat holds. It is not a card, though a card may stand in for it, and the
abilities it grants sit on the player. It is split across several modules, and the split follows
the rules rather than the history.

## Who holds it

{attr}`GameState.favor_holder <yasuki_core.engine.rules.state.GameState.favor_holder>` is a seat
or None. Everything else reads that.

A card on the table represents it, and `rulebook/favor_proxy.py` is the only place that card is
made or unmade:

```python
def sync_proxy(game: GameState) -> None:
    """Make the Imperial Favor's proxy card match ``favor_holder``.

    The card is a rendering of the state, never the other way round: the Favor is not a card, though
    it may be represented by one, and its abilities sit on the player rather than on it (Twenty
    Festivals CR, The Imperial Favor). So this is the only place the proxy is created or destroyed,
    and nothing else under ``rules/`` reads it to answer a question about who holds the Favor.
    ...
    """
```

A rules function that asks the board who holds the Favor has the direction backwards. Ask
`favor_holder`.

## What the Favor buys

`rulebook/favor_abilities.py` holds the rulebook's own Favor abilities, registered by key:

```python
@favor_ability("send_attacker_home", cost=_choose_attacker)
def _send_attacker_home(game: GameState, seat: PlayerId) -> list[Effect]:
```

Which abilities exist at all is arc configuration. {func}`~.available_favor_abilities` intersects
what `ruleset.ACTIVE` lists with what this engine implements, so an arc naming an ability nobody has
written yet offers nothing instead of failing.

The `cost` argument is the ability's own price, on top of the Favor. The module states why it goes
there and not in the effects:

```python
# The whole cost goes in the cost builder, never half of it here and half in the effects: an
# ability is offered only when ``can_pay`` judges its cost payable, and a cost hidden among the
# effects is a cost nothing checks.
FAVOR_ABILITY_COSTS: dict[str, "FavorAbilityEffects"] = {}
FAVOR_ABILITY_EFFECTS: dict[str, "FavorAbilityEffects"] = {}
```

## Paying with the Favor

Holding the Favor is one way to pay a Favor cost. It is not the only way:

```python
def favor_payment_options(game: GameState, seat: PlayerId) -> dict[str, list[Effect]]:
    """Every way ``seat`` could pay a Favor cost right now, keyed by the option it reads as.

    Good Faith 0.4 lets a Favor action's player control the Favor "or have an alternate effect,
    substitute, or waiver", so holding it is one payer among several rather than the only one.
    """
```

A card that can pay for somebody registers `@favor_payer`, keyed by printed id. Every source that
could pay is offered together, the way the Pay Costs step offers every Gold producer. With one payer
there is nothing to ask, and with none the cost is unpayable and the ability is never offered.

{attr}`GameState.action_is_favor <yasuki_core.engine.rules.state.GameState.action_is_favor>` marks
the action in progress as a Favor action, which is what {class}`~.PayFavorCost` sets.

## Lobby is beside the Favor, not inside it

`rulebook/lobby.py` is a separate module because Lobby is a separate rule. It shares the payment
machinery and nothing else.

The registries hanging off it answer different questions. `@lobby_bonus_grant` adds to
what a seat's Lobby is worth. `@lobby_bar` is a predicate saying a seat may not Lobby at all.
`register_may_not_lobby` is a flag taking a card out of the Lobby pool. A card that changes Lobby
is almost always one line in one of the three.

## Where a card plugs in

Through `@favor_payer` to pay somebody's Favor cost, and through the Lobby registries.
[The Favor and the court](../../contributing/the_favor_and_the_court.md) is the same ground from a
card author's side.
