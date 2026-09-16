from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine.registrar import FlagRegistry, HandlerRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import Ability, Interrupt, InvestAbility
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.gold.discounts import effective_invest_discount
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import AbilityGrant
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
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
_INTERRUPTS: dict[str, Interrupt] = {}


@dataclass(frozen=True, slots=True)
class EntryState:
    """The state a card is in as it enters play. Arriving in a state is not a change of state: a
    card entering play bowed did not bow (CR, Bowed and Unbowed), so nothing announces it and no
    card reacts to it.

    Attributes
    ----------
    bowed : bool or None
        Whether the card arrives bowed. None leaves whatever was decided before this one. Default
        None.
    dishonorable : bool or None
        Whether the Personality arrives dishonorable. None leaves his status as it stands, since
        entering play does not change it (CR, Honorable and Dishonorable). Default None.
    """

    bowed: bool | None = None
    dishonorable: bool | None = None

    def over(self, base: "EntryState") -> "EntryState":
        """This state laid over ``base``: every field set here wins, and the rest are ``base``'s."""
        return EntryState(
            bowed=base.bowed if self.bowed is None else self.bowed,
            dishonorable=base.dishonorable if self.dishonorable is None else self.dishonorable,
        )


# Cards whose own text says what state they enter play in ("Enters play unbowed", "Gakuya enters
# play dishonorable"). The handler answers for the card, given the game, and its answer is laid over
# the rulebook's default.
EntryStateHandler = Callable[[GameState, L5RCard], EntryState]
ENTRY_STATES: HandlerRegistry[EntryStateHandler] = HandlerRegistry(
    "entry states", "already names the state it enters play in"
)
entry_state = ENTRY_STATES.make_decorator()


def entry_state_of(game: GameState, card: L5RCard) -> EntryState:
    """The state ``card`` enters play in: the rulebook's default, a Holding bowed and anything else
    unbowed with its status unchanged, under whatever the card's own text says."""
    default = EntryState(bowed=isinstance(card.printed, HoldingPrint))
    handler = ENTRY_STATES.get(card.printed_id)
    return default if handler is None else handler(game, card).over(default)


# Personalities whose text says they cannot attack: the Attacker may not assign them to a
# battlefield, and nothing stops them defending.
_CANNOT_ATTACK = FlagRegistry("cannot attack", "already cannot attack")
register_cannot_attack = _CANNOT_ATTACK.make_register()


# Cards with something to do before they enter play ("Before Gonshiro enters play, dishonor him").
# The handler's effects resolve while the card still stands where it came from, and the card
# arrives once that cascade has settled. Unlike an entry state, these are effects: they announce
# themselves and other cards react.
BeforeEnteringPlay = Callable[[GameState, L5RCard], list[Effect]]
BEFORE_ENTERING_PLAY: HandlerRegistry[BeforeEnteringPlay] = HandlerRegistry(
    "before entering play", "already acts before entering play"
)
before_entering_play = BEFORE_ENTERING_PLAY.make_decorator()


def effects_before_entering_play(game: GameState, card: L5RCard) -> list[Effect]:
    """The effects ``card``'s own text resolves before it enters play, or none."""
    handler = BEFORE_ENTERING_PLAY.get(card.printed_id)
    return [] if handler is None else handler(game, card)


@dataclass(frozen=True, slots=True)
class RecruitTiming:
    """A designator a card lets itself be Recruited under besides the rulebook's Dynasty, with the
    ability keywords that Recruit then carries ("You may Recruit this Holding as a Political Open
    action").

    Attributes
    ----------
    timing : ActionTiming
        The designator the Recruit may be taken under.
    keywords : frozenset of str, optional
        The ability keywords that Recruit carries. Default empty.
    """

    timing: ActionTiming
    keywords: frozenset[str] = frozenset()


RECRUIT_TIMINGS: HandlerRegistry[RecruitTiming] = HandlerRegistry(
    "recruit timings", "already names a Recruit timing"
)
register_recruit_timing = RECRUIT_TIMINGS.make_register()


def recruit_timing_of(game: GameState, card_id: str) -> RecruitTiming | None:
    """The Recruit timing ``card_id``'s text adds, or None when it Recruits only as the rulebook
    allows or is no longer on the table."""
    card = game.table.cards_by_id.get(card_id)
    return None if card is None else RECRUIT_TIMINGS.get(card.printed_id)


# Cards in play that give another card's abilities Tireless ("Your Stronghold's printed abilities
# have Tireless while this Holding is unbowed"). The handler says whether ``card``'s abilities are
# Tireless under the granting card, given the game.
TirelessGrant = Callable[[GameState, L5RCard, L5RCard], bool]
TIRELESS_GRANTS: HandlerRegistry[TirelessGrant] = HandlerRegistry(
    "tireless grants", "already grants Tireless"
)
tireless_grant = TIRELESS_GRANTS.make_decorator()


def granted_tireless(game: GameState, card: L5RCard) -> bool:
    """Whether a card in play gives ``card``'s abilities Tireless right now."""
    return any(
        grant(game, granting, card)
        for granting in game.table.battlefield.cards
        if (grant := TIRELESS_GRANTS.get(granting.printed_id)) is not None
    )


# The ability a card grants, built from the context its granting action recorded ("While a target
# Personality opposes Kaede, she has 'Battle: Ranged 3'"). One per granting card: the record names
# the card, and the card's factory says what it gives.
AbilityFactory = Callable[[tuple[str, ...]], Ability]
GRANTED_ABILITIES: HandlerRegistry[AbilityFactory] = HandlerRegistry(
    "granted abilities", "already grants an ability"
)
granted_ability = GRANTED_ABILITIES.make_decorator()


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


def may_attack(card: L5RCard) -> bool:
    """Whether ``card``'s text leaves it able to attack, which is what lets the Attacker assign
    it."""
    return card.printed_id not in _CANNOT_ATTACK


def register_invest(printed_id: str, value: InvestAbility) -> None:
    """Register ``value`` as ``printed_id``'s Invest ability."""
    if printed_id in _INVEST:
        raise ValueError(f"{printed_id} already has an invest ability")
    _INVEST[printed_id] = value


def register_interrupt(printed_id: str, value: Interrupt) -> None:
    """Register ``value`` as ``printed_id``'s Interrupt."""
    if printed_id in _INTERRUPTS:
        raise ValueError(f"{printed_id} already has an interrupt")
    _INTERRUPTS[printed_id] = value


def interrupt_for(card: L5RCard) -> Interrupt | None:
    """The Interrupt registered for ``card``'s printed id, or None."""
    return _INTERRUPTS.get(card.printed_id)


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


def abilities_for(game: GameState, card: L5RCard) -> tuple[Ability, ...]:
    """Every activated ability ``card`` has right now: the ones registered for its printed id, in
    registration order, then the ones recorded grants give it, in the order they were granted."""
    printed = _ABILITIES.get(card.printed_id, ())
    granted = tuple(
        GRANTED_ABILITIES[game.table.cards_by_id[grant.source_id].printed_id](grant.context)
        for grant in game.ongoing
        if isinstance(grant, AbilityGrant)
        and grant.target_id == card.id
        and grant_applies(game, grant)
    )
    return (*printed, *granted)


def ability_for(game: GameState, card: L5RCard, key: str | None = None) -> Ability | None:
    """The activated ability ``key`` names on ``card``, or None if no ability it has answers to it.

    ``key`` is None for a card with one ability, which is the only one it could mean. Raise
    ValueError when a card with several is asked without a key, because the caller is holding an
    action that failed to say which ability it takes.
    """
    registered = abilities_for(game, card)
    if key is not None:
        return next((held for held in registered if held.key == key), None)
    if len(registered) > 1:
        raise ValueError(f"{card.printed_id} prints several abilities; name one by key")
    return next(iter(registered), None)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)
