from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneRole
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.attachments import attached_to
from yasuki_core.engine.rules.economy import effective_keywords
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Destroy,
    Effect,
    GrantModifier,
    Unpayable,
)
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint

# A cost is the effects paid to activate an ability, applied before the ability's own effects. Bow /
# destroy / spend-a-token are all just effects targeting a card, so costs and effects share one
# vocabulary — there is no separate cost taxonomy. What a card calls a cost is one here only when it
# must be paid before resolution; anything the card's own text sequences is an effect. A cost takes
# the board as well as the source because it may be paid by a card the source did not choose: an
# attachment's cost is usually paid by the Personality it hangs on, which only the graph can name.
Cost = Callable[[GameState, L5RCard], list[Effect]]


def no_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """An ability that costs nothing to announce."""
    return []


def bow_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Bow(source.id)]


def bow_parent_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Personality ``source`` is attached to. Unpayable while it is attached to none."""
    parent = attached_to(game, source)
    if parent is None:
        return [Unpayable(f"{source.id} is attached to no Personality")]
    return [Bow(parent.id)]


def bow_parent_and_destroy(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow the Personality ``source`` is attached to and destroy ``source``. Unpayable while it is
    attached to none."""
    return [*bow_parent_cost(game, source), Destroy(source.id, source.owner)]


def destroy_cost(game: GameState, source: L5RCard) -> list[Effect]:
    return [Destroy(source.id, source.owner)]


def spend_wealth(game: GameState, source: L5RCard) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, -1)]


def bow_and_destroy(game: GameState, source: L5RCard) -> list[Effect]:
    return [Bow(source.id), Destroy(source.id, source.owner)]


def banish_top_fate(game: GameState, source: L5RCard) -> list[Effect]:
    return [BanishTopFate(source.owner)]


def can_pay(game: GameState, card: L5RCard, cost: Cost) -> bool:
    """Whether ``card`` can pay ``cost``: every effect it spends is payable against the current
    state. Each effect owns its own precondition, so a new cost effect needs no change here."""
    return all(effect.is_payable(game) for effect in cost(game, card))


class CardLocation(str, Enum):
    """Where a card must be for its behavior to be offered. Distinct from ``ZoneRole``, which
    cannot name the battlefield — that is a field of its own on the table, not a keyed zone."""

    BATTLEFIELD = "battlefield"
    PROVINCE = "province"


@dataclass(frozen=True, slots=True)
class Ability:
    """An activated ability, on a card in play or on one waiting face-up in a Province.

    Attributes
    ----------
    timing : ActionTiming
        The designator printed on the card, saying when the ability may be used and by whom.
    label : str
        A short human description for the activation menu.
    cost : callable
        Maps ``(game, source_card)`` to the effects paid to activate — applied before the ability's
        own.
    targets : callable
        Maps ``(game, source_card)`` to the ids of the cards the ability may target — empty when
        none are legal, which also means the ability can't be offered.
    effects : callable
        Maps ``(game, source_card, target_card)`` to the effects the ability emits against a
        target.
    all_targets : bool
        Whether the ability hits every card ``targets`` returns rather than one chosen among them —
        an untargeted "your other Farms" grant instead of a single pick. Default False.
    located_at : tuple of CardLocation, optional
        Where the card has to be for the ability to be offered. An Event acts from the Province it
        sits face-up in, never from play. Default the battlefield alone.
    """

    timing: ActionTiming
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]]
    all_targets: bool = False
    located_at: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,)


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
        Maps ``(game, source_card, amount_paid)`` to the effects the Invest emits once the card
        enters play. It takes the board because an Invest may search a zone for what it fetches.
    """

    minimum: int
    maximum: int
    effect: Callable[[GameState, L5RCard, int], list[Effect]]


def itself(game: GameState, source: L5RCard) -> list[str]:
    """The target list of an ability that names no target: its own card. Paired with
    ``all_targets``, so the ability resolves against itself without asking the seat to pick the only
    card it could mean."""
    return [source.id]


def no_effects(card: L5RCard) -> list[Effect]:
    """A boost that costs its producer nothing."""
    return []


@dataclass(frozen=True, slots=True)
class ProductionBoost:
    """A producer's optional extra Gold yield, taken as it bows to pay, and what that costs.

    Three cards carry one and no two agree on the price, which is why the price belongs to the card
    rather than to the payment path.

    Attributes
    ----------
    amount : int
        The extra Gold the producer adds when its controller takes the boost.
    effects : callable, optional
        Maps the producer to the price it pays for boosting — Outlying Farms destroys itself, Slave
        Pits loses its controller 2 Honor. These resolve once the producer has yielded; a card whose
        price must wait for the rest of the cascade returns a ``Then``. Default no effects.
    """

    amount: int
    effects: Callable[[L5RCard], list[Effect]] = no_effects


# Cards their controller may leave bowed rather than straightening at the start of their turn (the
# printed "May remain bowed"), by printed id. A flag rather than a handler: the card states the
# permission and says nothing about when it is worth taking, which is the controller's business.
MAY_REMAIN_BOWED: set[str] = set()


def may_remain_bowed(printed_id: str) -> None:
    """Register ``printed_id`` as a card the turn-start straighten passes over."""
    MAY_REMAIN_BOWED.add(printed_id)


def left_bowed(game: GameState, seat: PlayerId) -> frozenset[str]:
    """The cards ``seat`` controls that the turn-start straighten leaves alone."""
    return frozenset(
        card.id
        for card in game.table.battlefield.cards
        if card.owner is seat and card.printed_id in MAY_REMAIN_BOWED
    )


_ABILITIES: dict[str, Ability] = {}
_INVEST: dict[str, InvestAbility] = {}
_PRODUCTION_BOOST: dict[str, ProductionBoost] = {}


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


def register_production_boost(printed_id: str, boost: ProductionBoost) -> None:
    """Register ``boost`` as ``printed_id``'s optional bow-time yield increase."""
    if printed_id in _PRODUCTION_BOOST:
        raise ValueError(f"{printed_id} already has a production boost")
    _PRODUCTION_BOOST[printed_id] = boost


def fixed_invest_amount(card: L5RCard) -> int | None:
    """The Invest cost ``card`` charges when that cost is fixed, or None when it prints no Invest or
    lets the payer size one. A caller that cannot raise a "how much?" decision treats both alike."""
    ability = _INVEST.get(card.printed_id)
    if ability is None or ability.minimum != ability.maximum:
        return None
    return ability.minimum


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)


def production_boost_for(card: L5RCard) -> ProductionBoost | None:
    """The boost ``card`` may take as it bows to produce, or None if it has none."""
    return _PRODUCTION_BOOST.get(card.printed_id)


def _seat_cards(game: GameState, seat: PlayerId) -> Iterator[tuple[CardLocation, L5RCard]]:
    """Every card ``seat`` could activate something on, with where it is sitting."""
    for card in game.table.battlefield.cards:
        if card.owner is seat:
            yield CardLocation.BATTLEFIELD, card
    for key, zone in game.table.zones.items():
        if key.owner is seat and key.role is ZoneRole.PROVINCE:
            for card in zone.cards:
                if card.face_up:  # face-down, what the card is has not been revealed
                    yield CardLocation.PROVINCE, card


def activatable(
    game: GameState, seat: PlayerId, permitted: frozenset[ActionTiming]
) -> list[L5RCard]:
    """The cards ``seat`` may activate an ability on right now: controlled, sitting somewhere the
    ability acts from, its designator among ``permitted``, its cost payable, and with at least one
    legal target."""
    ready: list[L5RCard] = []
    for location, card in _seat_cards(game, seat):
        ability = _ABILITIES.get(card.printed_id)
        if ability is None or ability.timing not in permitted:
            continue
        if location not in ability.located_at:
            continue
        if not can_pay(game, card, ability.cost):
            continue
        if ability.targets(game, card):
            ready.append(card)
    return ready


def owned_personalities(game: GameState, owner: PlayerId) -> tuple[L5RCard, ...]:
    """The Personalities ``owner`` has in play — the pool almost every "your target Personality"
    starts from, before the card's own condition narrows it."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint) and card.owner is owner
    )


def owned_holdings(game: GameState, owner: PlayerId, keyword: str | None = None) -> list[L5RCard]:
    """The Holdings ``owner`` has in play, narrowed to those carrying ``keyword`` when one is given.
    Default None, which takes them all."""
    return [
        held
        for held in game.table.battlefield.cards
        if held.owner is owner
        and isinstance(held.printed, HoldingPrint)
        and (keyword is None or keyword in effective_keywords(game, held))
    ]


def plus_one_gp_this_turn(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]
