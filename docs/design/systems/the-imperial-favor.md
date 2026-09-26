# The Imperial Favor

The Favor is a thing one seat holds. It is not a card, though a card may stand in for it, and the
abilities it grants sit on the player. It is split across several modules, and the split follows
the rules rather than the history.

## Who holds it

{attr}`GameState.favor_holder <yasuki_core.engine.rules.state.GameState.favor_holder>` is a seat
or None. Everything else reads that.

A card on the table represents it, and `rulebook/favor_proxy.py` is the only place that card is
made or unmade. (A rulebook *ability* is represented differently: conferred by a keyword on the
card it spends, as the Kharmic abilities are, or held by a proxy dealt once into the seat's
rulebook zone by `rulebook/proxies.py`, as the Favor's own abilities are.)

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

The rulebook's own Favor abilities sit on a Favor ability proxy, which `rulebook/proxies.py` deals
into each seat's rulebook zone. It is a different card from the Favor in the holder's hand, which
stays a rendering of `favor_holder` and carries no ability, because an ability without a keyword on
a hand card would be played rather than activated. `rulebook/favor_abilities.py` registers each
ability on its proxy as an ordinary `Ability` with `from_rulebook` set, its designator and keywords
as the rulebook prints them, and the printed text as its label.

The proxy an arc deals decides which abilities exist. `ONYX` names the Onyx Favor proxy in
`rulebook_proxies`, carrying the datasheet's two Political abilities, and `SHATTERED_EMPIRE`
inherits it. `IMPERIAL` names the pre-Gold proxy, carrying Soul of the Empire's four uses, all
Political. Three are abilities. The fourth, preventing a Family Honor loss, is an `Interrupt`
registered on the same proxy, which answers any player's loss and costs the Favor. No proxy ability
names a `ruleset`.

An ability's whole price goes in its cost, the Favor and anything else it charges:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/favor_abilities.py
:start-at: def _favor_cost(extra: SeatCost | None)
:end-before: def _on_your_turn(
:language: python
```

A choice that names what the ability acts on is in the cost, so an ability with nothing to name is
withheld. A Wind in play makes the cost unpayable, and no payer can answer it. "If it is your turn"
is in the targets: the proxy targets itself only while its seat is active.
{func}`~.is_favor_ability` recognizes the actions by key and proxy, and the Tk client lists them on
the Favor card in the holder's hand.

## Paying with the Favor

Holding the Favor is one way to pay a Favor cost. It is not the only way:

```{literalinclude} ../../../src/yasuki_core/engine/rules/rulebook/favor_payment.py
:start-at: def favor_payment_options(game: GameState, seat: PlayerId) -> dict[str, list[Effect]]:
:end-before: payers: dict[str, list[Effect]] = {}
:language: python
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
