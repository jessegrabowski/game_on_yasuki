from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeGuard

from yasuki_core.engine import ops
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.invest import invest_effects
from yasuki_core.engine.rules.abilities.idioms import declare_amount
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation
from yasuki_core.engine.rules.abilities.registry import (
    EntryState,
    effects_before_entering_play,
    entry_state_of,
    invest_amounts,
    register_location_ability,
)
from yasuki_core.engine.rules.board.queries import province_key_holding, province_zones
from yasuki_core.engine.rules.effects import (
    AdjustCounter,
    Ask,
    Attributed,
    Effect,
    GainHonor,
    PayGold,
    Recruit,
    RefillProvince,
    SpendSeatOncePerTurn,
    Unpayable,
)
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseFortificationProvince,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay, GameEvent
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.legality import PROCLAIM, can_proclaim, recruit_cost
from yasuki_core.engine.rules.rulebook.copies import copy_may_enter
from yasuki_core.engine.rules.rulebook.recruit_restrictions import may_recruit
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming, ActivateAbility
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.work import Provenance
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY
from yasuki_core.game_pieces.prints import HoldingPrint, PersonalityPrint


@dataclass(frozen=True, slots=True)
class ResolveRecruit:
    """Finish a Recruit once its cost is paid: resolve what the card does before entering play,
    then bring it from its province into play and refill the vacated province.

    Attributes
    ----------
    seat : PlayerId
        The recruiting seat.
    card_id : str
        The card leaving its province for play.
    invest_amount : int or None
        The gold Invested while recruiting, driving the card's one-time Invest effect on entry, or
        None when the recruit took no Invest. A free Invest is an amount of zero, not None. Default
        None.
    renew : bool
        Whether to refill the vacated province face-up (a granted Renew), on top of the card's own
        Renew keyword. Default False.
    proclaim : bool
        Whether the recruit is Proclaimed, claiming the seat's once-per-turn Proclaim and adding the
        Personality's Personal Honor to its Family Honor after entry. Default False.
    """

    seat: PlayerId
    card_id: str
    invest_amount: int | None = None
    renew: bool = False
    proclaim: bool = False

    def resume(self, game: GameState) -> None:
        resolve_recruit(
            game,
            seat=self.seat,
            card_id=self.card_id,
            invest_amount=self.invest_amount,
            renew=self.renew,
            proclaim=self.proclaim,
        )


def announce_recruit(
    game: GameState,
    card: L5RCard | L5RCard,
    seat: PlayerId,
    invest_amount: int | None,
    renew: bool = False,
    proclaim: bool = False,
) -> ChoosePayment | None:
    """Queue the recruit and build the payment it must be paid with, or None for a recruit that
    costs nothing."""
    game.stack.append(ResolveRecruit(seat, card.id, invest_amount, renew, proclaim))
    amount = recruit_cost(game, card) + (invest_amount or 0)
    if amount == 0:
        return None
    return payment_request(game, seat, amount, card.name, target=card)


def resolve_recruit(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    invest_amount: int | None = None,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    """Hand the Recruit's effects to the action once its cost is paid, held at the Interrupt step
    (CR, Action Sequence step D). A Fortification Recruited from anywhere but a Province asks its
    controller which Province it will attach to first (CR, Fortification)."""
    card = game.table.cards_by_id[card_id]
    from_province = province_key_holding(game, seat, card_id)
    if from_province is None and keywords.FORTIFICATION in effective_keywords(game, card):
        game.pending = ChooseFortificationProvince(
            seat=seat,
            candidates=_province_slots(game, seat),
            source_card_id=card_id,
            invest_amount=invest_amount,
            proclaim=proclaim,
        )
        return
    arrival = Recruit(
        card_id,
        from_province=from_province,
        invest_amount=invest_amount,
        renew=renew,
        proclaim=proclaim,
    )
    triggers.resolve_action_effects(game, recruit_effects(game, arrival))


def recruit_effects(game: GameState, arrival: Recruit) -> list[Effect]:
    """What a Recruit resolves: the card's own effects before it enters play, while it still stands
    where it is, then ``arrival`` once their cascade has settled. The card's own effects are its
    trait's rather than the action's, so they are not open to the Interrupt step (CR, Traits)."""
    card = game.table.cards_by_id[arrival.card_id]
    before = effects_before_entering_play(game, card)
    return [*(Attributed(effect, Provenance()) for effect in before), arrival]


def _province_slots(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Every one of ``seat``'s Provinces, named by slot. A Province is a slot rather than the card
    standing in it, so an empty one is as attachable as any other (CR, Fortification)."""
    return tuple(key.token for key, _ in province_zones(game, seat))


def apply_fortification_province(
    game: GameState, request: ChooseFortificationProvince, response: DecisionResponse
) -> None:
    """Recruit the waiting Fortification, attaching it to the Province the seat named."""
    arrival = Recruit(
        request.source_card_id,
        from_province=None,
        fortifies=ZoneKey.from_token(response.choices[0]),
        invest_amount=request.invest_amount,
        proclaim=request.proclaim,
    )
    triggers.resolve_action_effects(game, recruit_effects(game, arrival))


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
    keyword), its Invest, a Proclaim's Honor gain, and the refill of the Province it left.

    The Invest comes before the Proclaim's gain, which can pause for an Honor Interrupt. The two
    never combine, since a Recruit cannot both Invest and Proclaim.
    """
    card = game.table.cards_by_id[arrival.card_id]
    effects: list[Effect] = []
    held = card.counters.get(SINCERITY.key, 0)
    if held:
        effects.append(AdjustCounter(card.id, SINCERITY, -held))
    effects.extend(invest_effects(game, card, arrival.invest_amount))
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
    and nothing does for a seat that ignores Honor Requirements."""
    seat = source.owner
    if not isinstance(source.printed, HoldingPrint | PersonalityPrint):
        return []
    if not copy_may_enter(game, seat, source) or not may_recruit(game, seat, source):
        return []
    if isinstance(source.printed, PersonalityPrint) and not _meets_honor_requirement(game, source):
        return []
    return [source.id]


def _meets_honor_requirement(game: GameState, personality: L5RCard) -> bool:
    seat = game.table.seats[personality.owner]
    required = personality.honor_requirement
    return seat.ignores_honor_requirements or required is None or seat.honor >= required


def recruit_gold(game: GameState, source: L5RCard) -> list[Effect]:
    """The Gold Recruiting ``source`` costs, paid for the card, or nothing for a card that costs
    nothing."""
    amount = recruit_cost(game, source)
    if amount == 0:
        return []
    return [PayGold(source.owner, amount, source.name, target_id=source.id)]


def recruit_from_its_province(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    """Recruit ``source`` from the Province it stands in."""
    return recruit_effects(game, _arrival(game, source))


def _arrival(
    game: GameState, card: L5RCard, *, invest_amount: int | None = None, proclaim: bool = False
) -> Recruit:
    return Recruit(
        card.id,
        from_province=province_key_holding(game, card.owner, card.id),
        invest_amount=invest_amount,
        proclaim=proclaim,
    )


def _proclaimable(game: GameState, source: L5RCard) -> list[str]:
    return recruitable(game, source) if can_proclaim(game, source) else []


def _recruit_and_proclaim(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    return recruit_effects(game, _arrival(game, source, proclaim=True))


def _investable(game: GameState, source: L5RCard) -> list[str]:
    return recruitable(game, source) if invest_amounts(game, source) is not None else []


def _recruit_with_invest_gold(game: GameState, source: L5RCard) -> list[Effect]:
    """The Gold Cost and the Invest, paid together for the card (CR, Invest). An Invest the payer
    sizes is declared first."""
    amounts = invest_amounts(game, source)
    if amounts is None:
        return [Unpayable(f"{source.id} prints no Invest")]
    if len(amounts) > 1:
        question = f"Invest how much Gold in {source.name}?"
        declared = declare_amount(source, amounts, question)
        return [replace(declared, alongside=recruit_cost(game, source), target_id=source.id)]
    amount = recruit_cost(game, source) + amounts[0]
    if amount == 0:
        return []
    return [PayGold(source.owner, amount, source.name, target_id=source.id)]


def _recruit_with_invest(game: GameState, source: L5RCard, target: L5RCard) -> list[Effect]:
    amounts = invest_amounts(game, source) or ()
    invested = amounts[0] if len(amounts) == 1 else game.amount_declared
    return recruit_effects(game, _arrival(game, source, invest_amount=invested))


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
    _recruit_with_invest,
)
