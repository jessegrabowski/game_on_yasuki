from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.state import GameState, Phase
from yasuki_core.engine.rules.triggers import (
    AdjustCounter,
    BanishTopFate,
    Bow,
    Destroy,
    DrawCard,
    Effect,
    GrantModifier,
    Straighten,
    province_holdings,
    sincerity_seed_targets,
)
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.counters import SINCERITY, WEALTH
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


def _bow_and_destroy(source: L5RCard) -> list[Effect]:
    return [Bow(source.id), Destroy(source.id)]


def _banish_top_fate(source: L5RCard) -> list[Effect]:
    return [BanishTopFate(source.owner)]


def can_pay(game: GameState, card: L5RCard, cost: Cost) -> bool:
    """Whether ``card`` can pay ``cost`` — every effect it spends can actually apply: a bow needs the
    card unbowed, a counter spend needs enough of that counter, a Fate-deck banish needs a card to
    banish. Any other cost effect always applies."""
    for effect in cost(card):
        match effect:
            case Bow() if card.bowed:
                return False
            case AdjustCounter(counter=counter, delta=delta) if delta < 0:
                if card.counters.get(counter.key, 0) < -delta:
                    return False
            case BanishTopFate(seat=seat):
                if not game.table.decks[DeckKey(seat, Side.FATE)].cards:
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
        Maps ``(source_card, target_card)`` to the effects the ability emits against a target.
    all_targets : bool
        Whether the ability hits every card ``targets`` returns rather than one chosen among them —
        an untargeted "your other Farms" grant instead of a single pick. Default False.
    recruits_target : bool
        Whether the ability recruits its chosen target (paying for it and bringing it into play)
        rather than emitting ``effects`` against it — Modest Farm's out-of-sequence recruit. Default
        False.
    """

    phase: Phase
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[L5RCard, L5RCard], list[Effect]]
    all_targets: bool = False
    recruits_target: bool = False


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


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)


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


def _owned_holdings(game: GameState, owner: PlayerId, keyword: str) -> list[DynastyHolding]:
    return [
        held
        for held in game.table.battlefield.cards
        if held.owner is owner and isinstance(held, DynastyHolding) and keyword in held.keywords
    ]


def _owned_farms(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in _owned_holdings(game, card.owner, "Farm")]


def _other_farms(game: GameState, card: L5RCard) -> list[str]:
    return [farm.id for farm in _owned_holdings(game, card.owner, "Farm") if farm is not card]


def _owned_markets(game: GameState, card: L5RCard) -> list[str]:
    return [market.id for market in _owned_holdings(game, card.owner, "Market")]


def _owned_ports(game: GameState, card: L5RCard) -> list[str]:
    return [port.id for port in _owned_holdings(game, card.owner, "Port")]


def _sincerity_seed_targets(game: GameState, card: L5RCard) -> list[str]:
    return sincerity_seed_targets(game, card.owner)


def _province_holdings(game: GameState, card: L5RCard) -> list[str]:
    return province_holdings(game, card.owner)


def _no_effects(source: L5RCard, target: L5RCard) -> list[Effect]:
    return []  # a recruits_target ability routes to the recruit flow, never to effects


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


def _seed_sincerity(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [AdjustCounter(target.id, SINCERITY, 1)]


def _plus_one_gp_this_turn(source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


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
    "harvested_land": Ability(
        phase=Phase.ACTION,
        label="Bow, destroy: give your other Farms +1 Gold Production",
        cost=_bow_and_destroy,
        targets=_other_farms,
        effects=_plus_one_gp_this_turn,
        all_targets=True,
    ),
    "ichiba_district": Ability(
        phase=Phase.ACTION,
        label="Banish a Fate card: give a Port +1 Gold Production",
        cost=_banish_top_fate,
        targets=_owned_ports,
        effects=_plus_one_gp_this_turn,
    ),
    "shrine_of_sincerity": Ability(
        phase=Phase.DYNASTY,
        label="Bow: seed a Sincerity token onto a Province Sincerity card",
        cost=_bow,
        targets=_sincerity_seed_targets,
        effects=_seed_sincerity,
    ),
    "modest_farm": Ability(
        phase=Phase.ACTION,
        label="Bow, pay a Holding's cost: recruit it from your Province out of sequence",
        cost=_bow,
        targets=_province_holdings,
        effects=_no_effects,
        recruits_target=True,
    ),
}


def _invest_wealth(source: L5RCard, amount: int) -> list[Effect]:
    """One +1GP Wealth token per gold invested — Rebuilt Harbor's variable payoff."""
    return [AdjustCounter(source.id, WEALTH, amount)]


def _two_wealth(source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 2)]


def _one_wealth(source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]


# Per-card Invest abilities, registered on import. Courts of Otosan Uchi also creates a Courtier
# Personality, deferred until personalities are recruitable; only its Wealth token is modeled.
_INVEST: dict[str, InvestAbility] = {
    "questionable_market": InvestAbility(minimum=2, maximum=2, effect=_two_wealth),
    "rebuilt_harbor": InvestAbility(minimum=1, maximum=3, effect=_invest_wealth),
    "training_court": InvestAbility(minimum=1, maximum=1, effect=_one_wealth),
    "courts_of_otosan_uchi": InvestAbility(minimum=2, maximum=2, effect=_one_wealth),
}
