from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.triggers import (
    AdjustCounter,
    Bow,
    Destroy,
    DrawCard,
    Effect,
    GrantModifier,
    Straighten,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding

# A cost is the effects paid to activate an ability, applied to the source card before the ability's
# own effects. Bow / destroy / spend-a-token are all just effects targeting the source, so costs and
# effects share one vocabulary — there is no separate cost taxonomy.
Cost = Callable[[L5RCard], list[Effect]]


def _bow(source: L5RCard) -> list[Effect]:
    return [Bow(source.id)]


def _destroy(source: L5RCard) -> list[Effect]:
    return [Destroy(source.id)]


def _spend_wealth(source: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, -1)]


def can_pay(card: L5RCard, cost: Cost) -> bool:
    """Whether ``card`` can pay ``cost`` — every effect it spends can actually apply: a bow needs the
    card unbowed, a counter spend needs enough of that counter. Any other cost effect always
    applies."""
    for effect in cost(card):
        match effect:
            case Bow() if card.bowed:
                return False
            case AdjustCounter(counter=counter, delta=delta) if delta < 0:
                if card.counters.get(counter.key, 0) < -delta:
                    return False
    return True


@dataclass(frozen=True, slots=True)
class Ability:
    """An activated ability on an in-play card.

    Attributes
    ----------
    phase : Phase
        The phase the ability may be used in.
    label : str
        A short human description for the activation menu.
    cost : callable
        Maps the source card to the effects paid to activate — applied before the ability's own.
    targets : callable
        Maps ``(game, source_card)`` to the ids of the cards the ability may target — empty when
        none are legal, which also means the ability can't be offered.
    effects : callable
        Maps ``(source_card, target_card)`` to the effects the ability emits once its target is
        chosen.
    """

    phase: Phase
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[L5RCard, L5RCard], list[Effect]]


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def activatable(game: GameState, seat: PlayerId, phase: Phase) -> list[L5RCard]:
    """The in-play cards ``seat`` may activate an ability on right now: controlled, its ability legal
    in ``phase``, its cost payable, and with at least one legal target."""
    ready: list[L5RCard] = []
    for card in game.table.battlefield.cards:
        if card.owner is not seat:
            continue
        ability = _ABILITIES.get(card.printed_id)
        if ability is None or ability.phase is not phase:
            continue
        if not can_pay(card, ability.cost):
            continue
        if ability.targets(game, card):
            ready.append(card)
    return ready


def _owned_holdings(game: GameState, owner: PlayerId, keyword: str) -> list[DynastyHolding]:
    return [
        held
        for held in game.table.battlefield.cards
        if held.owner is owner and isinstance(held, DynastyHolding) and keyword in held.keywords
    ]


def _owned_farms(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in _owned_holdings(game, card.owner, "Farm")]


def _owned_markets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in _owned_holdings(game, card.owner, "Market")]


def _owned_bowed_farms(game: GameState, card: L5RCard) -> list[str]:
    # "Not produced Gold this turn" is satisfied for any bowed Farm: production only happens in the
    # Dynasty phase, after this Open ability's Action-phase window.
    return [farm.id for farm in _owned_holdings(game, card.owner, "Farm") if farm.bowed]


def _millet_farm_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 2, Duration.UNTIL_END_OF_TURN)
    ]


def _otokoshi_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [DrawCard(source.owner), AdjustCounter(target.id, WEALTH, 1)]


def _rural_market_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [Straighten(target.id)]


# Per-card activated abilities, registered on import.
_ABILITIES: dict[str, Ability] = {
    "millet_farm": Ability(
        phase=Phase.ACTION,
        label="Bow: give a Farm +2 Gold Production",
        cost=_bow,
        targets=_owned_farms,
        effects=_millet_farm_effects,
    ),
    "otokoshi_district": Ability(
        phase=Phase.ACTION,
        label="Destroy: draw a card and give a Market a wealth token",
        cost=_destroy,
        targets=_owned_markets,
        effects=_otokoshi_effects,
    ),
    "rural_market": Ability(
        phase=Phase.ACTION,
        label="Spend a wealth token: straighten a Farm",
        cost=_spend_wealth,
        targets=_owned_bowed_farms,
        effects=_rural_market_effects,
    ),
}
