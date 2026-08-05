from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Destroy,
    Effect,
    GrantModifier,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.dynasty import DynastyHolding

# A cost is the effects paid to activate an ability, applied to the source card before the ability's
# own effects. Bow / destroy / spend-a-token are all just effects targeting the source, so costs and
# effects share one vocabulary — there is no separate cost taxonomy.
Cost = Callable[[L5RCard], list[Effect]]


def bow_cost(source: L5RCard) -> list[Effect]:
    return [Bow(source.id)]


def destroy_cost(source: L5RCard) -> list[Effect]:
    return [Destroy(source.id)]


def spend_wealth(source: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, -1)]


def bow_and_destroy(source: L5RCard) -> list[Effect]:
    return [Bow(source.id), Destroy(source.id)]


def banish_top_fate(source: L5RCard) -> list[Effect]:
    return [BanishTopFate(source.owner)]


def can_pay(game: GameState, card: L5RCard, cost: Cost) -> bool:
    """Whether ``card`` can pay ``cost``: every effect it spends is payable against the current
    state. Each effect owns its own precondition, so a new cost effect needs no change here."""
    return all(effect.is_payable(game) for effect in cost(card))


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
        Maps ``(source_card, target_card)`` to the effects the ability emits against a target.
    all_targets : bool
        Whether the ability hits every card ``targets`` returns rather than one chosen among them —
        an untargeted "your other Farms" grant instead of a single pick. Default False.
    """

    phase: Phase
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[L5RCard, L5RCard], list[Effect]]
    all_targets: bool = False


@dataclass(frozen=True, slots=True)
class InvestAbility:
    """A card's Invest ability — an optional gold cost paid while recruiting for a one-time enter-play
    effect (the kicker-style second purchase option).

    Attributes
    ----------
    minimum : int
        The least gold the Invest may cost; equals ``maximum`` for a fixed Invest.
    maximum : int
        The most gold the Invest may cost; above ``minimum`` for a variable Invest whose amount the
        recruiting seat chooses.
    effect : callable
        Maps ``(source_card, amount_paid)`` to the effects the Invest emits once the card enters play.
    """

    minimum: int
    maximum: int
    effect: Callable[[L5RCard, int], list[Effect]]


_ABILITIES: dict[str, Ability] = {}
_INVEST: dict[str, InvestAbility] = {}
_PRODUCTION_BOOST: dict[str, int] = {}


def register_ability(printed_id: str, value: Ability) -> None:
    """Register ``value`` as ``printed_id``'s activated ability."""
    if printed_id in _ABILITIES:
        raise ValueError(f"{printed_id} already has an ability")
    _ABILITIES[printed_id] = value


def register_invest(printed_id: str, value: InvestAbility) -> None:
    """Register ``value`` as ``printed_id``'s Invest ability."""
    if printed_id in _INVEST:
        raise ValueError(f"{printed_id} already has an invest ability")
    _INVEST[printed_id] = value


def register_production_boost(printed_id: str, extra_gold: int) -> None:
    """Register ``printed_id`` as a producer that may raise its yield by ``extra_gold`` as it bows to
    pay, and is destroyed for having done so."""
    if printed_id in _PRODUCTION_BOOST:
        raise ValueError(f"{printed_id} already has a production boost")
    _PRODUCTION_BOOST[printed_id] = extra_gold


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)


def production_boost_for(card: L5RCard) -> int | None:
    """The extra Gold ``card`` may add as it bows to produce, or None if it has no boost. A boostable
    producer is destroyed after it bows boosted — Outlying Farms is the sole case."""
    return _PRODUCTION_BOOST.get(card.printed_id)


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
        if not can_pay(game, card, ability.cost):
            continue
        if ability.targets(game, card):
            ready.append(card)
    return ready


def owned_holdings(game: GameState, owner: PlayerId, keyword: str) -> list[DynastyHolding]:
    return [
        held
        for held in game.table.battlefield.cards
        if held.owner is owner and isinstance(held, DynastyHolding) and keyword in held.keywords
    ]


def plus_one_gp_this_turn(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]
