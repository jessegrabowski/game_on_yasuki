from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeGuard

from yasuki_core.ruleset import in_force
from yasuki_core.engine.registrar import FlagRegistry, HandlerRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.model import (
    Ability,
    CardLocation,
    Interrupt,
    InvestAbility,
)
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.gold.discounts import effective_invest_discount
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.stats.ongoing_grants import grant_applies
from yasuki_core.engine.rules.vocabulary.modifiers import AbilityGrant, Ongoing, SeatAbilityGrant
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.text_split import split_text_box
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
# The abilities a keyword confers on every card carrying it, by the keyword's lowercase form.
KEYWORD_ABILITIES: dict[str, tuple[Ability, ...]] = {}
# The abilities the rulebook confers on every card sitting at a location, by the location.
LOCATION_ABILITIES: dict[CardLocation, tuple[Ability, ...]] = {}
_INVEST: dict[str, InvestAbility] = {}
_INTERRUPTS: dict[str, tuple[Interrupt, ...]] = {}
# The Interrupts a keyword confers on every card carrying it, by the keyword's lowercase form.
KEYWORD_INTERRUPTS: dict[str, tuple[Interrupt, ...]] = {}


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


# The ability a card grants, built for the card that holds it from the context its granting action
# recorded ("While a target Personality opposes Kaede, she has 'Battle: Ranged 3'"). One per
# granting card: the record names the card, and the card's factory says what it gives.
AbilityFactory = Callable[[GameState, L5RCard, tuple[str, ...]], Ability]
GRANTED_ABILITIES: HandlerRegistry[AbilityFactory] = HandlerRegistry(
    "granted abilities", "already grants an ability"
)
granted_ability = GRANTED_ABILITIES.make_decorator()


def ability_registrations(*, ruleset_name: str | None = None) -> dict[str, tuple[Ability, ...]]:
    """Every printed id with the registered abilities in force for it under one ruleset.

    Parameters
    ----------
    ruleset_name : str, optional
        The name of the ruleset asked about. Default the active ruleset's.
    """
    in_force_by_id = {
        printed_id: tuple(held for held in registered if in_force(held, ruleset_name=ruleset_name))
        for printed_id, registered in _ABILITIES.items()
    }
    return {printed_id: held for printed_id, held in in_force_by_id.items() if held}


def _read_together(one: Ability | Interrupt, other: Ability | Interrupt) -> bool:
    """Whether some ruleset reads both abilities, which is when their keys have to differ."""
    return None in (one.ruleset, other.ruleset) or one.ruleset == other.ruleset


def register_ability(printed_id: str, value: Ability) -> None:
    """Register ``value`` as one of ``printed_id``'s activated abilities.

    A card printing several needs a ``Ability.key`` on each, since an action names the ability
    it takes by key and an unkeyed one could not be told from its sibling. Raise ValueError if a
    second ability arrives unkeyed, or if it repeats a key already registered for the card. Two
    abilities naming different rulesets are never read together, so they do not collide.
    """
    registered = _ABILITIES.get(printed_id, ())
    beside = [held for held in registered if _read_together(held, value)]
    if beside:
        if any(held.key is None for held in (*beside, value)):
            raise ValueError(f"{printed_id} prints several abilities, so each one needs a key")
        if any(held.key == value.key for held in beside):
            raise ValueError(f"{printed_id} already has an ability keyed {value.key!r}")
    _ABILITIES[printed_id] = (*registered, value)


def register_keyword_ability(value: Ability) -> None:
    """Register ``value`` as one of the abilities its ``from_keyword`` confers on every card carrying
    that keyword.

    Raise ValueError for an ability naming no keyword or no key: it sits beside whatever the card
    prints, so an action has to name it by key to tell the two apart.
    """
    if value.from_keyword is None:
        raise ValueError("a keyword ability names the keyword that confers it")
    if value.key is None:
        raise ValueError(f"the {value.from_keyword} ability needs a key")
    keyword = value.from_keyword.lower()
    registered = KEYWORD_ABILITIES.get(keyword, ())
    if any(held.key == value.key and _read_together(held, value) for held in registered):
        raise ValueError(f"{value.from_keyword} already confers an ability keyed {value.key!r}")
    KEYWORD_ABILITIES[keyword] = (*registered, value)


def register_location_ability(value: Ability) -> None:
    """Register ``value`` as an ability the rulebook confers on every card sitting at any of its
    ``located_at``.

    Raise ValueError for an ability not marked ``from_rulebook``, or naming no key, for the reason
    :func:`~.register_keyword_ability` gives.
    """
    if not value.from_rulebook:
        raise ValueError("a location ability is marked from_rulebook")
    if value.key is None:
        raise ValueError("a location ability needs a key")
    for location in value.located_at:
        registered = LOCATION_ABILITIES.get(location, ())
        if any(held.key == value.key and _read_together(held, value) for held in registered):
            raise ValueError(f"{location.value} already confers an ability keyed {value.key!r}")
        LOCATION_ABILITIES[location] = (*registered, value)


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
    """Register ``value`` as ``printed_id``'s Interrupt. Raise ValueError if the card already has
    one read under the same ruleset."""
    registered = _INTERRUPTS.get(printed_id, ())
    if any(_read_together(held, value) for held in registered):
        raise ValueError(f"{printed_id} already has an interrupt")
    _INTERRUPTS[printed_id] = (*registered, value)


def register_keyword_interrupt(value: Interrupt) -> None:
    """Register ``value`` as an Interrupt its ``from_keyword`` confers on every card carrying that
    keyword.

    Raise ValueError for an Interrupt naming no keyword or no key, for the reason
    :func:`~.register_keyword_ability` gives, or repeating a key the keyword already confers.
    """
    if value.from_keyword is None:
        raise ValueError("a keyword Interrupt names the keyword that confers it")
    if value.key is None:
        raise ValueError(f"the {value.from_keyword} Interrupt needs a key")
    keyword = value.from_keyword.lower()
    registered = KEYWORD_INTERRUPTS.get(keyword, ())
    if any(held.key == value.key and _read_together(held, value) for held in registered):
        raise ValueError(f"{value.from_keyword} already confers an Interrupt keyed {value.key!r}")
    KEYWORD_INTERRUPTS[keyword] = (*registered, value)


def interrupts_for(game: GameState, card: L5RCard) -> tuple[Interrupt, ...]:
    """Every Interrupt ``card`` offers right now: the one it prints, in force under the active
    ruleset, then those every keyword it carries confers."""
    printed = _printed_interrupt(card)
    conferred = _by_keyword(game, card, KEYWORD_INTERRUPTS)
    return conferred if printed is None else (printed, *conferred)


def interrupt_for(card: L5RCard, key: str | None = None) -> Interrupt | None:
    """The Interrupt keyed ``key`` that ``card`` was taken with, or None.

    The card's own Interrupt answers to its key, None for one registered without. Any other key is
    looked up among the keyword Interrupts whether or not the card still carries the keyword, since
    an Interrupt taken against an effect applies when the effect comes up even if the card lost the
    keyword in between.
    """
    printed = _printed_interrupt(card)
    if printed is not None and printed.key == key:
        return printed
    if key is None:
        return None
    return next(
        (
            held
            for registered in KEYWORD_INTERRUPTS.values()
            for held in registered
            if held.key == key and in_force(held)
        ),
        None,
    )


def _printed_interrupt(card: L5RCard) -> Interrupt | None:
    return next((held for held in _INTERRUPTS.get(card.printed_id, ()) if in_force(held)), None)


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
    """Every activated ability ``card`` has right now: the ones registered for its printed id and
    in force under the active ruleset, in registration order, then the ones recorded grants give
    it or every card of its owner's, in the order they were granted, then the ones its keywords
    confer, then the ones the rulebook confers on every card where it sits. A conferred ability
    yields to a granted one under the same key, which is how a card changes a rulebook ability for
    a while."""
    printed = tuple(held for held in _ABILITIES.get(card.printed_id, ()) if in_force(held))
    granted = tuple(
        GRANTED_ABILITIES[game.table.cards_by_id[grant.source_id].printed_id](
            game, card, grant.context
        )
        for grant in game.ongoing
        if _grants_to(grant, card) and grant_applies(game, grant)
    )
    shadowed = {held.key for held in granted}
    conferred = tuple(held for held in _conferred(game, card) if held.key not in shadowed)
    return (*printed, *granted, *conferred)


def _grants_to(recorded: Ongoing, card: L5RCard) -> TypeGuard[AbilityGrant | SeatAbilityGrant]:
    if isinstance(recorded, AbilityGrant):
        return recorded.target_id == card.id
    return isinstance(recorded, SeatAbilityGrant) and recorded.seat is card.owner


def _conferred(game: GameState, card: L5RCard) -> tuple[Ability, ...]:
    return (*_by_keyword(game, card, KEYWORD_ABILITIES), *_by_location(game, card))


def _by_keyword[T: Ability | Interrupt](
    game: GameState, card: L5RCard, registry: dict[str, tuple[T, ...]]
) -> tuple[T, ...]:
    """What ``registry`` confers on ``card`` through the keywords it carries, in force now."""
    if not registry:
        return ()
    carried = {keyword.lower() for keyword in effective_keywords(game, card)}
    return tuple(
        held
        for keyword, conferred in registry.items()
        if keyword in carried
        for held in conferred
        if in_force(held)
    )


def _by_location(game: GameState, card: L5RCard) -> tuple[Ability, ...]:
    return tuple(
        held
        for location, conferred in LOCATION_ABILITIES.items()
        if _sits_at(game, card, location)
        for held in conferred
        if in_force(held)
    )


_LOCATION_ZONE_ROLES = {
    CardLocation.PROVINCE: ZoneRole.PROVINCE,
    CardLocation.HAND: ZoneRole.HAND,
    CardLocation.RULEBOOK: ZoneRole.RULEBOOK,
}


def _sits_at(game: GameState, card: L5RCard, location: CardLocation) -> bool:
    if location is CardLocation.BATTLEFIELD:
        return any(held is card for held in game.table.battlefield.cards)
    role = _LOCATION_ZONE_ROLES[location]
    return any(
        key.role is role and any(held is card for held in zone.cards)
        for key, zone in game.table.zones.items()
    )


def ability_for(game: GameState, card: L5RCard, key: str | None = None) -> Ability | None:
    """The activated ability ``key`` names on ``card``, or None if no ability it has answers to it.

    ``key`` is None for the card's one unkeyed ability, or its only ability. Raise ValueError when
    a card with several keyed abilities is asked without a key, because the caller is holding an
    action that failed to say which it takes.
    """
    registered = abilities_for(game, card)
    if key is not None:
        return next((held for held in registered if held.key == key), None)
    unkeyed = [held for held in registered if held.key is None]
    if len(unkeyed) == 1:
        return unkeyed[0]
    if len(registered) > 1:
        raise ValueError(f"{card.printed_id} prints several abilities; name one by key")
    return next(iter(registered), None)


def invest_for(card: L5RCard) -> InvestAbility | None:
    """The Invest ability registered for ``card``'s printed id, or None."""
    return _INVEST.get(card.printed_id)


def printed_ability_line(card: L5RCard, index: int) -> str:
    """The ``index``-th ability ``card``'s text prints, as printed: prefix, icons and all.

    The card's name when its text prints no such ability, which a card built without its text
    does. The registration audit is what holds a real registration's index to the printing.
    """
    abilities = split_text_box(card.printed.text).abilities
    return abilities[index].printed if index < len(abilities) else card.name


def ability_label(card: L5RCard, ability: Ability) -> str:
    """What a client shows for ``ability`` on ``card``: its own ``label`` when it has one, and
    otherwise the printed ability it implements, read off the card's text."""
    if ability.label is not None:
        return ability.label
    return printed_ability_line(card, ability.printed_index)


def interrupt_label(card: L5RCard, interrupt: Interrupt[Effect]) -> str:
    """What a client shows for ``interrupt`` on ``card``, the way :func:`~.ability_label` does."""
    if interrupt.label is not None:
        return interrupt.label
    return printed_ability_line(card, interrupt.printed_index)
