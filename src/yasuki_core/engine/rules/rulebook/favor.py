from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import favor_abilities, triggers
from yasuki_core.engine.rules.actions import ActivateAbility, PlayStrategy
from yasuki_core.engine.rules.effects import (
    AskOption,
    DiscardFavor,
    Effect,
    PayFavorCost,
    Unpayable,
)
from yasuki_core.engine.rules.keyword_grants import effective_keywords
from yasuki_core.engine.rules.registrar import HandlerRegistry
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard


# What a card charges to pay somebody's Favor cost right now, or None when it cannot pay at all.
# Registered by printed id the way ``BOW_WAIVERS`` registers waivers, so a payer is a card behavior
# rather than a branch inside the cost.
FavorPayer = Callable[[GameState, L5RCard], list[Effect] | None]
FAVOR_PAYERS: HandlerRegistry[FavorPayer] = HandlerRegistry(
    "favor payers", "already pays Favor costs"
)
favor_payer = FAVOR_PAYERS.make_decorator()


FAVOR_PAYMENT = "favor_payment"
DISCARD_THE_FAVOR = "Discard the Imperial Favor"


def favor_payers(game: GameState, seat: PlayerId) -> dict[str, list[Effect]]:
    """Every way ``seat`` could pay a Favor cost right now, keyed by the option it reads as.

    Good Faith 0.4 lets a Favor action's player control the Favor "or have an alternate effect,
    substitute, or waiver", so holding it is one payer among several rather than the only one.
    """
    payers: dict[str, list[Effect]] = {}
    if game.favor_holder is seat:
        payers[DISCARD_THE_FAVOR] = [DiscardFavor(seat)]
    for card in game.table.battlefield.cards:
        payer = FAVOR_PAYERS.get(card.printed_id)
        if card.owner is not seat or payer is None:
            continue
        price = payer(game, card)
        if price is not None:
            payers[card.name] = price
    return payers


def favor_cost_for_seat(game: GameState, seat: PlayerId, source_id: str) -> list[Effect]:
    """The Favor cost ``seat`` pays: discard the Favor, or take one of the offers to pay it instead.

    Every source that could pay is offered together, the way the Pay Costs step offers every Gold
    producer, because that is where the CR settles who pays (CR, Action Sequence step B). With one
    payer there is nothing to ask, and with none the cost is unpayable and the ability is never
    offered.

    Takes the seat rather than a card because a rulebook Favor ability belongs to the player and has
    no card to charge it to.
    """
    payers = favor_payers(game, seat)
    if not payers:
        return [Unpayable(f"{seat.name} has no way to pay a Favor cost")]
    if len(payers) == 1:
        return [PayFavorCost(), *next(iter(payers.values()))]
    return [
        PayFavorCost(),
        AskOption(seat, tuple(payers), "Pay the Favor cost how?", FAVOR_PAYMENT, source_id),
    ]


def favor_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """The Favor cost on ``source``'s ability, in the shape a :data:`Cost` takes."""
    return favor_cost_for_seat(game, source.owner, source.id)


@choice_resolver(FAVOR_PAYMENT)
def _resolve_favor_payment(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Charge whichever payer the seat named."""
    return favor_payers(game, seat).get(chosen[0], [])


def is_favor_action(game: GameState) -> bool:
    """Whether the action now resolving is a Favor action.

    An action that pays a Favor cost is one. An action offering the Favor as one of two ways to pay
    is one only on the branch that takes it, which is why this is read after payment rather than off
    the announcement — unless the ability is designated Favor, which settles it either way (ShE
    datasheet, The Favor Icon). The designator belongs to the ability, so it is read only off an
    action taken from one.
    """
    if game.action_is_favor:
        return True
    # The keyword designates an ability, so it is read only off the actions taken from one. A card
    # carrying it is not turned into a Favor action by being recruited, equipped, or spent.
    if not isinstance(game.action, ActivateAbility | PlayStrategy):
        return False
    card = game.table.cards_by_id.get(game.action.card_id)
    return card is not None and keywords.FAVOR in effective_keywords(game, card)


def use_favor_ability(game: GameState, key: str) -> None:
    """Take one of the arc's rulebook Favor abilities: pay the Favor cost, then do what it does.

    The cost comes first because it is a cost — settled in the Pay Costs step, before the ability
    resolves (CR, Action Sequence).
    """
    seat = game.round.priority
    cost = favor_abilities.favor_ability_cost(game, seat, key)
    effects = favor_abilities.FAVOR_ABILITY_EFFECTS[key](game, seat)
    triggers.resolve_effects(game, [*cost, *effects])
