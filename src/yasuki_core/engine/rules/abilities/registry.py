from yasuki_core.engine.registrar import FlagRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, InvestAbility
from yasuki_core.engine.rules.gold.discounts import effective_invest_discount
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import HoldingPrint


# Cards their controller may leave bowed rather than straightening at the start of their turn (the
# printed "May remain bowed"), by printed id. A flag rather than a handler: the card states the
# permission and says nothing about when it is worth taking, which is the controller's business.
MAY_REMAIN_BOWED = FlagRegistry("may remain bowed", "may already remain bowed")
register_may_remain_bowed = MAY_REMAIN_BOWED.make_register()


def may_stay_bowed(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """The bowed cards ``seat`` controls that it may choose to keep bowed rather than straighten.

    Only the bowed ones: the choice is made before a card straightens, so one already standing has
    nothing to decline (CR, May Remain Bowed).
    """
    return tuple(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is seat and card.bowed and card.printed_id in MAY_REMAIN_BOWED
    )


_ABILITIES: dict[str, tuple[Ability, ...]] = {}
_INVEST: dict[str, InvestAbility] = {}
# The Holdings whose own text overrides the rule that a Holding enters play bowed. Registered from
# the set module the card lives in, like everything else a card does, rather than listed centrally,
# so the layout guard scans it and the card index checks it.
_ENTERS_UNBOWED = FlagRegistry("enters unbowed", "already enters play unbowed")
register_enters_unbowed = _ENTERS_UNBOWED.make_register()


def register_ability(printed_id: str, value: Ability) -> None:
    """Register ``value`` as one of ``printed_id``'s activated abilities.

    A card printing several needs a ``Ability.key`` on each, since an action names the ability
    it takes by key and an unkeyed one could not be told from its sibling. Raise ValueError if a
    second ability arrives unkeyed, or if it repeats a key already registered for the card.
    """
    registered = _ABILITIES.get(printed_id, ())
    if registered:
        if any(held.key is None for held in (*registered, value)):
            raise ValueError(f"{printed_id} prints several abilities, so each one needs a key")
        if any(held.key == value.key for held in registered):
            raise ValueError(f"{printed_id} already has an ability keyed {value.key!r}")
    _ABILITIES[printed_id] = (*registered, value)


def enters_play_bowed(card: L5RCard) -> bool:
    """Whether ``card`` bows as it enters play: every Holding but the few that say otherwise."""
    return isinstance(card.printed, HoldingPrint) and card.printed_id not in _ENTERS_UNBOWED


def register_invest(printed_id: str, value: InvestAbility) -> None:
    """Register ``value`` as ``printed_id``'s Invest ability."""
    if printed_id in _INVEST:
        raise ValueError(f"{printed_id} already has an invest ability")
    _INVEST[printed_id] = value


def invest_amounts(game: GameState, card: L5RCard) -> tuple[int, ...] | None:
    """The sums ``card``'s Invest may be paid for now: its printed amounts less whatever its own
    text discounts, floored at zero, or None when it prints no Invest.

    Two printed amounts a discount drives to the same price collapse to one, since paying it once
    can only buy one of the two things.

    Returns
    -------
    tuple of int or None
        The payable sums, least first, or None when the card prints no Invest.
    """
    ability = _INVEST.get(card.printed_id)
    if ability is None:
        return None
    discount = effective_invest_discount(game, card)
    if not discount:
        return ability.amounts
    return tuple(dict.fromkeys(max(0, amount - discount) for amount in ability.amounts))


def fixed_invest_amount(game: GameState, card: L5RCard) -> int | None:
    """The Invest cost ``card`` charges when that cost is fixed, or None when it prints no Invest or
    lets the payer size one. A caller that cannot raise a "how much?" decision treats both alike."""
    amounts = invest_amounts(game, card)
    if amounts is None or len(amounts) != 1:
        return None
    return amounts[0]


def abilities_for(card: L5RCard) -> tuple[Ability, ...]:
    """Every activated ability registered for ``card``'s printed id, in registration order."""
    return _ABILITIES.get(card.printed_id, ())


def ability_for(card: L5RCard, key: str | None = None) -> Ability | None:
    """The activated ability ``key`` names on ``card``, or None if no registered ability answers to
    it.

    ``key`` is None for a card printing one ability, which is the only one it could mean. Raise
    ValueError when a card printing several is asked without a key, because the caller is holding
    an action that failed to say which ability it takes.
    """
    registered = abilities_for(card)
    if key is not None:
        return next((held for held in registered if held.key == key), None)
    if len(registered) > 1:
        raise ValueError(f"{card.printed_id} prints several abilities; name one by key")
    return next(iter(registered), None)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)
