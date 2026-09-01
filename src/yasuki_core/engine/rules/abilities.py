from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import ZoneRole, location_of
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.actions import ActionTiming, BattleDesignator
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.attachments import attached_to, attachments_of
from yasuki_core.engine.rules.economy import effective_invest_discount, effective_keywords
from yasuki_core.engine.rules.state import once_per_turn, used_this_turn
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.units import has_presence, location_permits
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
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


# Attachments offering the Personality they are on a once-per-turn waiver of the cost of bowing to
# pay for one of his own abilities, keyed on the attachment's printed id.
BOW_WAIVERS: set[str] = set()
WAIVER_TAG = "bow_waiver"


def bow_waiver(printed_id: str) -> None:
    """Register ``printed_id`` as an attachment whose Personality may ignore a bow cost once a
    turn."""
    BOW_WAIVERS.add(printed_id)


def _waiver_on(game: GameState, card: L5RCard) -> L5RCard | None:
    """An attachment on ``card`` whose bow waiver is still unspent this turn, or None for none."""
    for attached in attachments_of(game, card):
        if attached.printed_id in BOW_WAIVERS and not used_this_turn(game, attached, WAIVER_TAG):
            return attached
    return None


def bow_cost(game: GameState, source: L5RCard) -> list[Effect]:
    """Bow ``source`` to pay for its own ability, offering any waiver it carries first.

    The waiver is only worth asking about while ``source`` still stands: what it buys is a
    Personality who has not bowed, and one already bowed cannot pay a bow cost at all (CR, Costs).
    """
    waiver = _waiver_on(game, source)
    if waiver is None or source.bowed:
        return [Bow(source.id)]
    return [
        Ask(
            source.owner,
            f"Ignore the cost of bowing {source.name}?",
            WAIVER_TAG,
            subjects=(waiver.id,),
            source_id=source.id,
        )
    ]


@choice_resolver(WAIVER_TAG)
def _resolve_bow_waiver(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Taking the waiver spends it and nothing bows; declining pays the cost as printed."""
    if not chosen:
        return [Bow(source_id)]
    once_per_turn(game, game.table.cards_by_id[chosen[0]], WAIVER_TAG)
    return []


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
    HAND = "hand"


@dataclass(frozen=True, slots=True)
class Ability:
    """An activated ability, on a card in play or on one waiting face-up in a Province.

    Attributes
    ----------
    timings : tuple of ActionTiming
        The designators printed on the card, saying when the ability may be used and by whom. A card
        printing more than one — "Battle/Open" — may be used in any round that permits any of them.
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
    battle : frozenset of BattleDesignator, optional
        The designators qualifying how the ability escapes the Rule of Presence or the Rules of
        Location during a battle. Default empty, which takes both rules as written.
    """

    timings: tuple[ActionTiming, ...]
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]]
    all_targets: bool = False
    located_at: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,)
    battle: frozenset[BattleDesignator] = frozenset()


@dataclass(frozen=True, slots=True)
class InvestAbility:
    """A card's Invest ability — an optional gold cost paid while recruiting for a one-time enter-play
    effect (the kicker-style second purchase option).

    Attributes
    ----------
    amounts : tuple of int
        Every sum the Invest may be paid for, least first. A single entry is a fixed Invest; several
        are the choice the recruiting seat makes, which a card prints either as a span ("Invest
        :g1: to :g3:") or as separate prices that buy different things ("Invest :g2: or :g6:").
    effect : callable
        Maps ``(game, source_card, amount_paid)`` to the effects the Invest emits once the card
        enters play. It takes the board because an Invest may search a zone for what it fetches.
    """

    amounts: tuple[int, ...]
    effect: Callable[[GameState, L5RCard, int], list[Effect]]


def itself(game: GameState, source: L5RCard) -> list[str]:
    """The target list of an ability that names no target: its own card. Paired with
    ``all_targets``, so the ability resolves against itself without asking the seat to pick the only
    card it could mean."""
    return [source.id]


# Cards their controller may leave bowed rather than straightening at the start of their turn (the
# printed "May remain bowed"), by printed id. A flag rather than a handler: the card states the
# permission and says nothing about when it is worth taking, which is the controller's business.
MAY_REMAIN_BOWED: set[str] = set()


def may_remain_bowed(printed_id: str) -> None:
    """Register ``printed_id`` as a card the turn-start straighten passes over."""
    MAY_REMAIN_BOWED.add(printed_id)


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


_ABILITIES: dict[str, Ability] = {}
_INVEST: dict[str, InvestAbility] = {}
# The Holdings whose own text overrides the rule that a Holding enters play bowed. Registered from
# the set module the card lives in, like everything else a card does, rather than listed centrally —
# so the layout guard scans it and the card index checks it.
_ENTERS_UNBOWED: set[str] = set()


def register_ability(printed_id: str, value: Ability) -> None:
    """Register ``value`` as ``printed_id``'s activated ability."""
    if printed_id in _ABILITIES:
        raise ValueError(f"{printed_id} already has an ability")
    _ABILITIES[printed_id] = value


def register_enters_unbowed(printed_id: str) -> None:
    """Register ``printed_id`` as a card that enters play unbowed despite being a Holding."""
    if printed_id in _ENTERS_UNBOWED:
        raise ValueError(f"{printed_id} already enters play unbowed")
    _ENTERS_UNBOWED.add(printed_id)


def enters_play_bowed(card: L5RCard) -> bool:
    """Whether ``card`` bows as it enters play — every Holding but the few that say otherwise."""
    return isinstance(card.printed, HoldingPrint) and card.printed_id not in _ENTERS_UNBOWED


def register_invest(printed_id: str, value: InvestAbility) -> None:
    """Register ``value`` as ``printed_id``'s Invest ability."""
    if printed_id in _INVEST:
        raise ValueError(f"{printed_id} already has an invest ability")
    _INVEST[printed_id] = value


def invest_amounts(game: GameState, card: L5RCard) -> tuple[int, ...] | None:
    """The sums ``card``'s Invest may be paid for now — its printed amounts less whatever its own
    text discounts, floored at zero — or None when it prints no Invest.

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


def ability_for(card: L5RCard) -> Ability | None:
    """The activated ability registered for ``card``'s printed id, or None."""
    return _ABILITIES.get(card.printed_id)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)


def _seat_cards(game: GameState, seat: PlayerId) -> Iterator[tuple[CardLocation, L5RCard]]:
    """Every card ``seat`` could activate something on, with where it is sitting.

    A card in hand is yielded like any other. Only an ability whose ``located_at`` names the hand is
    offered from there, and every ability defaults to the battlefield, so a card waiting to be played
    stays silent until one says otherwise.
    """
    for card in game.table.battlefield.cards:
        if card.owner is seat:
            yield CardLocation.BATTLEFIELD, card
    for key, zone in game.table.zones.items():
        if key.owner is not seat:
            continue
        if key.role is ZoneRole.PROVINCE:
            for card in zone.cards:
                if card.face_up:  # face-down, what the card is has not been revealed
                    yield CardLocation.PROVINCE, card
        elif key.role is ZoneRole.HAND:
            yield from ((CardLocation.HAND, card) for card in zone.cards)


# Where a card is when activating it is what its ability means. A card in hand is *played* rather
# than activated, and pays a Gold Cost to do it, so it answers to its own action and is left out of
# the default.
IN_PLAY: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD, CardLocation.PROVINCE)


def activatable(
    game: GameState,
    seat: PlayerId,
    permitted: frozenset[ActionTiming],
    *,
    at: tuple[CardLocation, ...] = IN_PLAY,
) -> list[L5RCard]:
    """The cards ``seat`` may use an ability on right now: controlled, sitting somewhere the ability
    acts from, its designator among ``permitted``, its cost payable, and with at least one legal
    target.

    ``at`` narrows which of those places count, and defaults to the ones a card is *in play* in.
    Playing a card out of hand asks for :data:`CardLocation.HAND` explicitly, because it is a
    different action with a cost of its own.
    """
    ready: list[L5RCard] = []
    # Presence is the seat's, not the card's, so it is settled once rather than per card offered.
    present = has_presence(game, seat)
    for location, card in _seat_cards(game, seat):
        if location not in at:
            continue
        ability = _ABILITIES.get(card.printed_id)
        if ability is None or permitted.isdisjoint(ability.timings):
            continue
        # The Rule of Presence is about the player, not the card, so it gates an action taken from
        # anywhere — a Strategy out of hand as much as a Personality on the board.
        if not present and BattleDesignator.ABSENT not in ability.battle:
            continue
        if ActionTiming.RESPONSE in ability.timings and card.id in game.responded:
            continue
        if location not in ability.located_at:
            continue
        # A card in a unit may only be acted from at the battlefield the battle is at (CR, Rules
        # of Location). A card in hand or in a Province is in no unit, and neither is a Holding.
        if (
            location is CardLocation.BATTLEFIELD
            and not _location_lifted(game, card, ability)
            and not location_permits(game, card)
        ):
            continue
        if not can_pay(game, card, ability.cost):
            continue
        if legal_targets(game, card, ability):
            ready.append(card)
    return ready


def _location_lifted(game: GameState, card: L5RCard, ability: Ability) -> bool:
    """Whether one of ``ability``'s designators excuses ``card`` from the Rules of Location (ShE
    datasheet).

    Remote reaches from home or from another battlefield; Home reaches from home alone, so a card
    standing at a battlefield that is not the current one is beyond it. Neither lifts the Rule of
    Presence.
    """
    if BattleDesignator.REMOTE in ability.battle:
        return True
    if BattleDesignator.HOME in ability.battle:
        return location_of(game.table, card).is_home
    return False


def has_absent_ability(game: GameState, seat: PlayerId) -> bool:
    """Whether ``seat`` holds any ability it could take with no presence at the current battlefield
    (ShE, Absent). What decides whether a seat with no units there is offered the opportunity at
    all, rather than skipped."""
    return any(
        (ability := _ABILITIES.get(card.printed_id)) is not None
        and BattleDesignator.ABSENT in ability.battle
        for _, card in _seat_cards(game, seat)
    )


def legal_targets(game: GameState, card: L5RCard, ability: Ability) -> list[str]:
    """The ids ``ability`` may target from ``card`` right now.

    Filtered centrally rather than by each card's own ``targets``: during a battle, a card in a unit
    may only be targeted at the battlefield the battle is at (CR, Rules of Location), and a handler
    that forgot to say so would be a silent rules bug on every card that forgot.
    """
    offered = ability.targets(game, card)
    attack = game.attack
    if attack is None or attack.current is None:
        return offered
    by_id = game.table.cards_by_id
    return [
        target_id
        for target_id in offered
        if target_id not in by_id or location_permits(game, by_id[target_id])
    ]


def owned_personalities(game: GameState, owner: PlayerId) -> tuple[L5RCard, ...]:
    """The Personalities ``owner`` has in play — the pool almost every "your target Personality"
    starts from, before the card's own condition narrows it."""
    return tuple(
        card
        for card in game.table.battlefield.cards
        if isinstance(card.printed, PersonalityPrint) and card.owner is owner
    )


def personalities_in_play(game: GameState) -> tuple[L5RCard, ...]:
    """Every Personality on the battlefield, either seat's — the pool a card means by "a target
    Personality" with no side attached to it."""
    return tuple(
        card for card in game.table.battlefield.cards if isinstance(card.printed, PersonalityPrint)
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
