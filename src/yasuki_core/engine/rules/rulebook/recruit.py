from collections.abc import Callable
from typing import TypeGuard

from yasuki_core.engine import ops
from yasuki_core.engine.registrar import FlagRegistry, HandlerRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.costs import priced_cost
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import (
    EntryState,
    effects_before_entering_play,
    entry_state_of,
    ability_for,
    invest_amounts,
    register_location_ability,
)
from yasuki_core.engine.rules.board.clans import shares_seat_alignment
from yasuki_core.engine.rules.board.queries import province_key_holding, province_zones
from yasuki_core.engine.rules.board.seats import cards_in_play
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    AskAmount,
    Attributed,
    Choose,
    Effect,
    GainHonor,
    Invest,
    PayGold,
    Recruit,
    RefillProvince,
    SpendSeatOncePerTurn,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay, GameEvent
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.legality import PROCLAIM, can_proclaim, recruit_cost
from yasuki_core.engine.rules.rulebook.joining import may_join
from yasuki_core.engine.rules.rulebook.recruit_restrictions import may_recruit
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey, controller_of
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint


def recruit_card(
    game: GameState, card: L5RCard, *, renew: bool = False, lowered_by: int = 0
) -> list[Effect]:
    """What a card's text that Recruits ``card`` resolves (CR, Recruit): the card's Gold Cost paid
    for it, since the action that calls for the Recruit gave no opportunity to pay, then its
    arrival. A Fortification Recruited from anywhere but a Province is attached to the Province its
    controller chooses (CR, Fortification). Nothing, not even the payment, for a card that may not
    enter play.

    Parameters
    ----------
    renew : bool, optional
        Whether the vacated Province refills face-up whatever the card's own Renew keyword says.
        Default False.
    lowered_by : int, optional
        Gold the Recruit costs less, for text that Recruits a card for less than its Gold Cost.
        Default 0.
    """
    seat = card.owner
    if not may_join(game, seat, card) or not may_recruit(game, seat, card):
        return []
    if not meets_honor_requirement(game, card):
        return []
    payment = recruit_gold(game, card, lowered_by=lowered_by)
    from_province = province_key_holding(game, seat, card.id)
    if from_province is None and keywords.FORTIFICATION in effective_keywords(game, card):
        slots = tuple(key.token for key, _ in province_zones(game, seat))
        return [*payment, Choose(seat, slots, 1, 1, FORTIFY, card.id)]
    arrival = Recruit(card.id, from_province=from_province, renew=renew)
    return [*payment, *recruit_effects(game, arrival)]


FORTIFY = "fortify"


@triggers.choice_resolver(FORTIFY, prompt="Choose a Province for the Fortification")
def _recruit_into_the_chosen_province(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Recruit the Fortification, attaching it to the Province the seat named. A Province is a
    slot rather than the card standing in it, so an empty one is as attachable as any other."""
    arrival = Recruit(source_id, from_province=None, fortifies=ZoneKey.from_token(chosen[0]))
    return recruit_effects(game, arrival)


def recruit_effects(game: GameState, arrival: Recruit) -> list[Effect]:
    """What a Recruit resolves: the card's own effects before it enters play, while it still stands
    where it is, then ``arrival`` once their cascade has settled. The card's own effects are its
    trait's rather than the action's, so they are not open to the Interrupt step (CR, Traits)."""
    card = game.table.cards_by_id[arrival.card_id]
    before = effects_before_entering_play(game, card)
    return [*(Attributed(effect, Provenance()) for effect in before), arrival]


def bring_into_play(game: GameState, arrival: Recruit) -> list[GameEvent]:
    """Move the Recruited card into play in its entry state, a Fortification attached to its
    Province, and announce that it was Recruited."""
    card = game.table.cards_by_id[arrival.card_id]
    # Enter unplaced so the client clusters the new card into the seat's home row by the stronghold,
    # rather than dropping it at the origin.
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    _arrive(card, entry_state_of(game, card))
    if keywords.FORTIFICATION in effective_keywords(game, card):
        province = arrival.fortifies if arrival.from_province is None else arrival.from_province
        if province is None:
            raise ValueError(
                f"{card.id} is a Fortification Recruited with no Province to attach to"
            )
        ops.attach_to_province(game.table, card, province)
    return [EnteredPlay(card.id, recruited=True)]


def _arrive(card: L5RCard, state: EntryState) -> None:
    """Put ``card`` in its entry state. Direct writes, since arriving in a state is not bowing or
    being dishonored (CR, Bowed and Unbowed) and nothing is announced."""
    if state.bowed:
        card.bow()
    if state.dishonorable is True:
        card.dishonor()
    elif state.dishonorable is False:
        card.rehonor()


def effects_after_entering_play(game: GameState, arrival: Recruit) -> list[Effect]:
    """What a Recruited card's arrival is followed by: its Sincerity tokens removed (Sincerity
    keyword), a Proclaim's Honor gain, and the refill of the Province it left."""
    card = game.table.cards_by_id[arrival.card_id]
    effects: list[Effect] = []
    held = card.counters.get(SINCERITY.key, 0)
    if held:
        effects.append(AdjustCounter(card.id, SINCERITY, -held))
    effects.extend(proclamation_effects(game, arrival))
    if arrival.from_province is not None:
        # Renew is read once the card has entered play, which is when the keyword speaks.
        renews = arrival.renew or keywords.RENEW in effective_keywords(game, card)
        effects.append(RefillProvince(arrival.from_province, face_up=renews))
    return effects


def proclamation_effects(game: GameState, arrival: Recruit) -> list[Effect]:
    """A Proclaimed Recruit's claim on the seat's once-per-turn Proclaim and its Honor gain, or
    nothing for a Recruit not Proclaimed."""
    if not arrival.proclaim:
        return []
    card = game.table.cards_by_id[arrival.card_id]
    return [SpendSeatOncePerTurn(card.owner, PROCLAIM), *proclaim_gain_effects(game, card)]


ProclaimGain = Callable[[GameState, L5RCard], int]

# Cards that may Proclaim for an amount other than their Personal Honor ("you may gain 3 Honor
# instead"). The handler returns the alternative, and the seat is asked which to take.
PROCLAIM_GAINS: HandlerRegistry[ProclaimGain] = HandlerRegistry(
    "proclaim gains", "already names a Proclaim gain"
)
proclaim_gain = PROCLAIM_GAINS.make_decorator()
PROCLAIM_GAIN_CHOICE = "proclaim_gain"


def proclaim_gain_effects(game: GameState, card: L5RCard) -> list[Effect]:
    """The Honor gain Proclaiming ``card`` earns its seat once it has entered play (CR, Proclaim):
    its Personal Honor, or a yes/no question when the card offers a different amount instead,
    since "may gain N instead" is the seat's call. No keeps the Personal Honor."""
    printed = effective_personal_honor(game, card)
    handler = PROCLAIM_GAINS.get(card.printed_id)
    if handler is None or handler(game, card) == printed:
        # The Recruit action targets the card, so a gain from Proclaiming a dishonorable Personality
        # rehonors him instead (CR, Rehonoring 0.1). His capped Personal Honor is 0, which is not a
        # gain, so only an alternative amount ever substitutes.
        return [GainHonor(card.owner, printed, personalities=(card.id,))]
    instead = handler(game, card)
    return [
        Ask(
            card.owner,
            f"Gain {instead} Honor from Proclaiming instead of {printed}?",
            PROCLAIM_GAIN_CHOICE,
            subjects=(card.id,),
            source_id=card.id,
        )
    ]


@triggers.choice_resolver(PROCLAIM_GAIN_CHOICE)
def _resolve_proclaim_gain(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Yes takes the alternative, no the Personal Honor. Both are read now, in play."""
    card = game.table.cards_by_id[source_id]
    amount = (
        PROCLAIM_GAINS[card.printed_id](game, card)
        if chosen
        else effective_personal_honor(game, card)
    )
    return [GainHonor(seat, amount, personalities=(card.id,))]


RECRUIT = "recruit"
RECRUIT_AND_PROCLAIM = "recruit_and_proclaim"
RECRUIT_WITH_INVEST = "recruit_with_invest"


def is_recruit(action: Action) -> TypeGuard[ActivateAbility]:
    """Whether ``action`` takes the rulebook Recruit ability on a Province card, Proclaimed,
    Invested or neither."""
    return isinstance(action, ActivateAbility) and action.ability_key in (
        RECRUIT,
        RECRUIT_AND_PROCLAIM,
        RECRUIT_WITH_INVEST,
    )


def recruitable(game: GameState, source: L5RCard) -> list[str]:
    """Itself, when its controller may Recruit it (CR, Recruit): a Holding or a Personality that
    the limits on copies and its own "May only be Recruited by" text let into play, and a
    Personality whose Honor Requirement its controller's Family Honor meets. A dash never withholds,
    and neither does a requirement the seat may ignore, whether for its lost Honor or for a card it
    controls that waives every requirement."""
    seat = source.owner
    if not isinstance(source.printed, HoldingPrint | PersonalityPrint):
        return []
    if not may_join(game, seat, source) or not may_recruit(game, seat, source):
        return []
    if not meets_honor_requirement(game, source):
        return []
    return [source.id]


# Cards whose controller may ignore every Personality's Honor Requirement, keyed on printed id.
# Read off the board as the Recruit is offered, so the waiver lasts exactly as long as the card
# stays in play.
HONOR_REQUIREMENT_WAIVERS = FlagRegistry(
    "honor requirement waivers", "already waives Honor Requirements"
)
register_honor_requirement_waiver = HONOR_REQUIREMENT_WAIVERS.make_register()


def meets_honor_requirement(game: GameState, card: L5RCard) -> bool:
    """Whether ``card``'s Honor Requirement lets its controller Recruit it: a dash never withholds,
    Family Honor that reaches it never withholds, and neither does a waiver. Only a Personality
    prints one at all, so every other card meets it."""
    if not isinstance(card.printed, PersonalityPrint):
        return True
    required = card.honor_requirement
    if required is None:
        return True
    seat = controller_of(game.table, card)
    if game.table.seats[seat].honor >= required:
        return True
    return _waives_honor_requirement(game, card)


def _waives_honor_requirement(game: GameState, personality: L5RCard) -> bool:
    """Whether anything lets ``personality``'s controller ignore its Honor Requirement (CR, Honor
    Requirement): Honor the seat has lost to anything but its own cards, which waives the
    requirement of its own Clan Alignment's Personalities only, or a card in play that waives every
    requirement whatever clan it names.

    "Its own cards" are the ones the seat controls, which the CR leaves open.
    """
    seat = controller_of(game.table, personality)
    if game.table.seats[seat].lost_honor_from_elsewhere and shares_seat_alignment(
        game, personality
    ):
        return True
    return any(card.printed_id in HONOR_REQUIREMENT_WAIVERS for card in cards_in_play(game, seat))


def recruit_gold(
    game: GameState, source: L5RCard, *, raised_by: int = 0, lowered_by: int = 0
) -> list[Effect]:
    """The Gold Recruiting ``source`` costs, paid for the card, or nothing for a card that costs
    nothing.

    Parameters
    ----------
    raised_by : int, optional
        Gold an Invest not yet laid is about to raise the card's Gold Cost by. Default 0.
    lowered_by : int, optional
        Gold the Recruit costs less, for text that Recruits a card for less than its Gold Cost.
        Default 0.
    """
    amount = recruit_cost(game, source, raised_by=raised_by, lowered_by=lowered_by)
    if amount == 0:
        return []
    return [PayGold(source.owner, amount, source.name, target_id=source.id)]


def recruit_from_its_province(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Recruit ``source`` from the Province it stands in."""
    return recruit_effects(game, _arrival(game, source))


def _arrival(game: GameState, card: L5RCard, *, proclaim: bool = False) -> Recruit:
    return Recruit(
        card.id, from_province=province_key_holding(game, card.owner, card.id), proclaim=proclaim
    )


def _proclaimable(game: GameState, source: L5RCard) -> list[str]:
    return recruitable(game, source) if can_proclaim(game, source) else []


def _recruit_and_proclaim(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return recruit_effects(game, _arrival(game, source, proclaim=True))


def _investable(game: GameState, source: L5RCard) -> list[str]:
    return recruitable(game, source) if invest_amounts(game, source) is not None else []


def _recruit_with_invest_gold(game: GameState, source: L5RCard) -> list[Effect]:
    """Name the Invest, which raises the card's Gold Cost before it is paid for (CR, Invest).
    Pricing the cost keeps on offer only the Invests its controller can pay for."""
    question = f"Invest how much Gold in {source.name}?"
    amounts = invest_amounts(game, source) or ()
    return [AskAmount(source.owner, amounts, question, INVEST_CHOICE, source.id)]


INVEST_CHOICE = "invest"


@triggers.choice_resolver(INVEST_CHOICE)
def _resolve_invest(
    game: GameState, source_id: str, chosen: tuple[str, ...], seat: PlayerId
) -> list[Effect]:
    """Invest the named amount in the card, then pay its Gold Cost so raised, priced as any
    Recruit's is."""
    card = game.table.cards_by_id[source_id]
    invested = int(chosen[0])
    ability = ability_for(game, card, RECRUIT_WITH_INVEST)
    if ability is None:
        raise ValueError(f"{card.id} carries no Recruit to Invest with")
    purchase = ability.purchase(game, card, plays_card=False)
    payment = priced_cost(game, purchase, recruit_gold(game, card, raised_by=invested))
    return [Invest(card.id, invested), *payment]


def _register_recruit(
    key: str,
    label: str,
    targets: Callable[[GameState, L5RCard], list[str]],
    cost: Callable[[GameState, L5RCard], list[Effect]],
    effects: Callable[[GameState, L5RCard, L5RCard], list[Effect]],
) -> None:
    register_location_ability(
        Ability(
            timings=(ActionTiming.DYNASTY,),
            label=label,
            cost=cost,
            targets=targets,
            effects=effects,
            hits_every_target=True,
            key=key,
            repeatable=True,
            located_at=(CardLocation.PROVINCE,),
            from_rulebook=True,
        )
    )


# Repeatable Dynasty, (pay Gold): bring a target face-up Personality or Holding from your Province
# into play (CR, Recruit). Proclaiming and Investing are chosen with the Recruit, so each is a way of
# taking it.
_register_recruit(RECRUIT, "Recruit", recruitable, recruit_gold, recruit_from_its_province)
_register_recruit(
    RECRUIT_AND_PROCLAIM, "Recruit & Proclaim", _proclaimable, recruit_gold, _recruit_and_proclaim
)
_register_recruit(
    RECRUIT_WITH_INVEST,
    "Recruit & Invest",
    _investable,
    _recruit_with_invest_gold,
    recruit_from_its_province,
)
