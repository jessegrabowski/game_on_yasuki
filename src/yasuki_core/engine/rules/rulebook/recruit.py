from collections.abc import Callable
from dataclasses import dataclass

from yasuki_core.engine import ops
from yasuki_core.engine.registrar import HandlerRegistry
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.invest import finish_invest
from yasuki_core.engine.rules.abilities.registry import enters_play_bowed, invest_amounts
from yasuki_core.engine.rules.board.queries import province_key_holding, province_zones
from yasuki_core.engine.rules.effects import Ask, Effect, GainHonor
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseFortificationProvince,
    ChooseInvestAmount,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.vocabulary.game_events import EnteredPlay
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.legality import proclaim_key, recruit_cost
from yasuki_core.engine.rules.turn.provinces import defer_refill
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.counters import SINCERITY


def recruit(
    game: GameState,
    card_id: str,
    invest: bool = False,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    """Announce a Recruit: defer bringing the card into play, then pause for its cost payment. The
    payment bows gold producers to cover :func:`~.recruit_cost` plus any Invest cost. Once answered,
    the stack resolves the move into play and the province refill.

    With ``invest`` set, also pay the card's Invest cost for its one-time enter-play effect. A fixed
    Invest folds straight into the payment. A variable one pauses first for
    :class:`~.ChooseInvestAmount` to pick how much to pay. With ``renew`` set, the vacated province
    refills face-up (a Renew granted by the recruiting effect). With ``proclaim`` set, claim the
    seat's once-per-turn Proclaim and add the Personality's Personal Honor to its Family Honor after
    it enters play (rules-skeleton section 6). Nothing is claimed until the payment resolves, so a
    cancelled Proclaim leaves it available. Raise ``ValueError`` if both ``invest`` and ``proclaim``
    are set. Invest belongs to Holdings and Proclaim to Personalities, so no card offers both."""
    if invest and proclaim:
        raise ValueError("a Recruit cannot both Invest and Proclaim")
    card = game.table.cards_by_id[card_id]
    seat = card.owner
    if not invest:
        game.pending = announce_recruit(
            game, card, seat, invest_amount=None, renew=renew, proclaim=proclaim
        )
        return
    amounts = invest_amounts(game, card)
    affordable = reachable_gold(game, seat, card) - recruit_cost(game, card)
    payable = tuple(amount for amount in amounts if amount <= affordable)
    if len(payable) == 1:
        game.pending = announce_recruit(game, card, seat, invest_amount=payable[0], renew=renew)
        return
    game.pending = ChooseInvestAmount(
        seat=seat,
        candidates=tuple(str(amount) for amount in payable),
        source_card_id=card_id,
    )


@dataclass(frozen=True, slots=True)
class ResolveRecruit:
    """Finish a Recruit once its cost is paid: bring the card from its province into play (bowed for
    a Holding) and refill the vacated province.

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
) -> ChoosePayment:
    """Queue the recruit and build the payment it must be paid with."""
    game.stack.append(ResolveRecruit(seat, card.id, invest_amount, renew, proclaim))
    amount = recruit_cost(game, card) + (invest_amount or 0)
    return payment_request(game, seat, amount, card.name, target=card)


def apply_invest_amount(
    game: GameState, request: ChooseInvestAmount, response: DecisionResponse
) -> None:
    card = game.table.cards_by_id[request.source_card_id]
    game.pending = announce_recruit(game, card, card.owner, invest_amount=int(response.choices[0]))


def resolve_recruit(
    game: GameState,
    seat: PlayerId,
    card_id: str,
    invest_amount: int | None = None,
    renew: bool = False,
    proclaim: bool = False,
) -> None:
    card = game.table.cards_by_id[card_id]
    # Read the Province before the move; afterwards no Province holds the card to look it up by.
    province_key = province_key_holding(game, seat, card_id)
    # Enter unplaced so the client clusters the new card into the seat's home row by the stronghold,
    # rather than dropping it at the origin.
    ops.move_card(game.table, card, BATTLEFIELD, position=UNPLACED_BOARD_POS)
    if enters_play_bowed(card):
        # Holdings enter play bowed; Personalities enter unbowed (rules-skeleton section 6).
        card.bow()
    fortification = keywords.FORTIFICATION in effective_keywords(game, card)
    if province_key is not None:
        if fortification:
            ops.attach_to_province(game.table, card, province_key)
        # Renew is read once the card has entered play, which is when the keyword speaks.
        renews = renew or keywords.RENEW in effective_keywords(game, card)
        defer_refill(game, province_key, face_up=renews)
    elif fortification:
        # Brought in from somewhere other than a Province, so its controller picks one (CR,
        # Fortification). Nothing is told it arrived until it has a Province to have arrived at.
        game.pending = ChooseFortificationProvince(
            seat=seat,
            candidates=_province_slots(game, seat),
            source_card_id=card_id,
            invest_amount=invest_amount,
            proclaim=proclaim,
        )
        return
    _announce_entering_play(game, card_id, invest_amount, proclaim)


def _province_slots(game: GameState, seat: PlayerId) -> tuple[str, ...]:
    """Every one of ``seat``'s Provinces, named by slot. A Province is a slot rather than the card
    standing in it, so an empty one is as attachable as any other (CR, Fortification)."""
    return tuple(key.token for key, _ in province_zones(game, seat))


def apply_fortification_province(
    game: GameState, request: ChooseFortificationProvince, response: DecisionResponse
) -> None:
    """Attach the waiting Fortification to the Province the seat named, then let it arrive."""
    card = game.table.cards_by_id[request.source_card_id]
    province = ZoneKey.from_token(response.choices[0])
    ops.attach_to_province(game.table, card, province)
    _announce_entering_play(game, card.id, request.invest_amount, request.proclaim)


@dataclass(frozen=True, slots=True)
class FinishRecruit:
    """The recruit steps that follow a card entering play: clearing its Sincerity tokens, resolving
    a Proclaim's honor gain, and applying any Invest effect. Deferred behind the ``EnteredPlay``
    cascade so a trait that pauses on entry (a Sincerity seed choice) resolves before them.

    Attributes
    ----------
    card_id : str
        The card that entered play.
    invest_amount : int or None
        The gold Invested while recruiting, driving the Invest effect, or None when the recruit took
        no Invest. A free Invest is an amount of zero, not None.
    proclaim : bool
        Whether the recruit was Proclaimed, so entry claims the once-per-turn Proclaim and adds the
        Personality's Personal Honor to its seat's Family Honor. Default False.
    """

    card_id: str
    invest_amount: int | None
    proclaim: bool = False

    def resume(self, game: GameState) -> None:
        finish_recruit(game, self.card_id, self.invest_amount, proclaim=self.proclaim)


def _announce_entering_play(
    game: GameState, card_id: str, invest_amount: int, proclaim: bool
) -> None:
    """The tail every recruited card shares: make the board legal, queue the post-entry steps, and
    announce the arrival."""
    # A card reaching the battlefield can make the board illegal, and the board is made legal
    # before anything is told the card arrived. A trigger that reads a state the rules say cannot
    # exist is deciding on a board that never legally existed.
    triggers.enforce_state_based_actions(game)
    # Defer the post-entry steps so an enter-play trait that pauses for a choice resolves first.
    game.stack.append(FinishRecruit(card_id, invest_amount, proclaim))
    triggers.fire(game, EnteredPlay(card_id))


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


def finish_recruit(
    game: GameState, card_id: str, invest_amount: int | None, proclaim: bool = False
) -> None:
    card = game.table.cards_by_id[card_id]
    _clear_sincerity(game, card)
    # The Invest before the Proclaim: the Proclaim's gain can pause for an Honor Interrupt, and
    # nothing may run behind a paused cascade. The two never combine, since ``recruit`` refuses
    # Invest with Proclaim, so the order changes nothing a card can observe.
    finish_invest(game, card, invest_amount)
    if proclaim:
        game.use_once(proclaim_key(card.owner, game.turn))
        triggers.resolve_action_effects(game, proclaim_gain_effects(game, card))


def _clear_sincerity(game: GameState, card: L5RCard) -> None:
    """Remove a card's Sincerity tokens once it has entered play, because its trait has already
    read them during the ``EnteredPlay`` cascade (Sincerity keyword)."""
    held = card.counters.get(SINCERITY.key, 0)
    if held:
        card.adjust_counter(SINCERITY.key, -held)
