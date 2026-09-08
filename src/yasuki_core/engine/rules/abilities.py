from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.modifiers import Duration, Stat
from yasuki_core.engine.rules.actions import (
    ActionTiming,
    BattleDesignator,
)
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.attachments import attached_to, attachments_of
from yasuki_core.engine.rules.keyword_grants import effective_keywords
from yasuki_core.engine.rules.gold.discounts import effective_invest_discount
from yasuki_core.engine.rules.board.clans import is_clan
from yasuki_core.engine.rules.state import once_per_turn, used_this_turn
from yasuki_core.engine.rules.triggers import choice_resolver
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    BanishTopFate,
    Bow,
    Destroy,
    Effect,
    GrantModifier,
    Discard,
    PutIntoPlay,
    Unpayable,
)
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import WEALTH
from yasuki_core.game_pieces.prints import HoldingPrint

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
    if printed_id in BOW_WAIVERS:
        raise ValueError(f"{printed_id} already waives a bow cost")
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


def register_edict(printed_id: str, *, clan: str | None = None) -> None:
    """Register ``printed_id``'s Open ability to put itself into play as an Edict.

    Every Edict prints the same action — put this into play, discard your other Edicts — so it is
    registered rather than written out per card. Discarding the others is the rulebook's own limit
    of one Edict at a time restated on the card (ShE datasheet, Edicts).

    Parameters
    ----------
    printed_id : str
        The Edict's printed id.
    clan : str, optional
        A clan its controller must be playing, for the Edicts that name one. Default None, for an
        Edict anyone may put into play.
    """

    def targets(game: GameState, source: L5RCard) -> list[str]:
        if clan is not None and not is_clan(game, source.owner, clan):
            return []
        return [source.id]

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        others = [
            card.id
            for card in game.table.battlefield.cards
            if card.owner is source.owner
            and card.id != source.id
            and keywords.EDICT in effective_keywords(game, card)
        ]
        return [
            PutIntoPlay(source.id),
            *(Discard(card_id, source.owner) for card_id in others),
        ]

    register_ability(
        printed_id,
        Ability(
            timings=(ActionTiming.OPEN,),
            label="Open: Put this Edict into play",
            cost=no_cost,
            targets=targets,
            effects=effects,
            all_targets=True,
            located_at=(CardLocation.HAND,),
        ),
    )


def register_event_entry(printed_id: str, *, timing: ActionTiming = ActionTiming.OPEN) -> None:
    """Register ``printed_id``'s "put this Event into play" action, taken from the Province it
    sits face-up in.

    Step F does not discard the card afterward because it is no longer where it was played from
    (CR, Action Sequence). The Province it vacates refills when the board settles, like any other.

    Parameters
    ----------
    printed_id : str
        The Event's printed id.
    timing : ActionTiming, optional
        The designator the entry is taken under. Default ``OPEN``, which most Events print.
    """

    def effects(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
        return [PutIntoPlay(source.id)]

    register_ability(
        printed_id,
        Ability(
            timings=(timing,),
            label=f"{timing.name.capitalize()}: Put this Event into play",
            cost=no_cost,
            targets=itself,
            effects=effects,
            all_targets=True,
            located_at=(CardLocation.PROVINCE,),
        ),
    )


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
    state. Each effect owns its own precondition, so a new cost effect needs no change here.

    Judged whole rather than effect by effect, because a cost's parts compete for the same cards:
    one that bows a Gold producer leaves it unable to bow again to pay the cost's own Gold half.
    """
    effects = cost(game, card)
    bowed = frozenset(effect.card_id for effect in effects if isinstance(effect, Bow))
    return all(effect.is_payable(game, bowed_by_cost=bowed) for effect in effects)


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
    targets_any_location : bool, optional
        Whether the ability reaches a target wherever it stands — the "at any location" a card
        prints, which lifts the Rules of Location off what it may be pointed at but not off the
        card it is taken from. Default False.
    key : str, optional
        Names this ability among the several its card prints, so an action can say which one it
        takes. A card printing one ability needs no key, because there is nothing to tell apart.
        Default None.
    tireless : bool, optional
        The Tireless keyword: the ability may be used even while its card is bowed (CR, Tireless).
        Default False, which leaves it to the rule that a bowed card's abilities cannot be used.
    """

    timings: tuple[ActionTiming, ...]
    label: str
    cost: Cost
    targets: Callable[[GameState, L5RCard], list[str]]
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]]
    all_targets: bool = False
    located_at: tuple[CardLocation, ...] = (CardLocation.BATTLEFIELD,)
    battle: frozenset[BattleDesignator] = frozenset()
    targets_any_location: bool = False
    key: str | None = None
    tireless: bool = False


@dataclass(frozen=True, slots=True)
class InvestAbility:
    """A card's Invest ability — an optional gold cost paid while recruiting for a one-time
    enter-play effect (the kicker-style second purchase option).

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
    if printed_id in MAY_REMAIN_BOWED:
        raise ValueError(f"{printed_id} may already remain bowed")
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


_ABILITIES: dict[str, tuple[Ability, ...]] = {}
_INVEST: dict[str, InvestAbility] = {}
# The Holdings whose own text overrides the rule that a Holding enters play bowed. Registered from
# the set module the card lives in, like everything else a card does, rather than listed centrally —
# so the layout guard scans it and the card index checks it.
_ENTERS_UNBOWED: set[str] = set()


def register_ability(printed_id: str, value: Ability) -> None:
    """Register ``value`` as one of ``printed_id``'s activated abilities.

    A card printing several needs a :attr:`Ability.key` on each, since an action names the ability
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


def plus_one_gp_this_turn(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return [
        GrantModifier(source.id, target.id, Stat.GOLD_PRODUCTION, 1, Duration.UNTIL_END_OF_TURN)
    ]


def one_wealth(game: GameState, source: L5RCard, amount: int) -> list[Effect]:
    return [AdjustCounter(source.id, WEALTH, 1)]
