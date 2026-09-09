from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.abilities.invest import finish_invest
from yasuki_core.engine.rules.abilities.registry import enters_play_bowed, invest_amounts
from yasuki_core.engine.rules.board.queries import province_key_holding, province_zones
from yasuki_core.engine.rules.decisions import (
    ChooseFortificationProvince,
    ChooseInvestAmount,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.gold.producers import reachable_gold
from yasuki_core.engine.rules.stats.keyword_grants import effective_keywords
from yasuki_core.engine.rules.legality import proclaim_key, recruit_cost
from yasuki_core.engine.rules.provinces import defer_refill
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.card_values import effective_personal_honor
from yasuki_core.engine.rules.work import FinishRecruit, ResolveRecruit
from yasuki_core.engine.table import BATTLEFIELD, UNPLACED_BOARD_POS, ZoneKey
from yasuki_core.game_pieces import keywords
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
    payment bows gold producers to cover :func:`recruit_cost` plus any Invest cost; once answered,
    the stack resolves the move into play and the province refill.

    With ``invest`` set, also pay the card's Invest cost for its one-time enter-play effect. A fixed
    Invest folds straight into the payment; a variable one pauses first for
    :class:`ChooseInvestAmount` to pick how much to pay. With ``renew`` set, the vacated province
    refills face-up (a Renew granted by the recruiting effect). With ``proclaim`` set, claim the
    seat's once-per-turn Proclaim and add the Personality's Personal Honor to its Family Honor after
    it enters play (rules-skeleton §6); nothing is claimed until the payment resolves, so a
    cancelled Proclaim leaves it available. Raise ``ValueError`` if both ``invest`` and ``proclaim``
    are set — Invest belongs to Holdings and Proclaim to Personalities, so no card offers both."""
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
    game.pending = None
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
        card.bow()  # Holdings enter play bowed; Personalities enter unbowed (rules-skeleton §6)
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
    game.pending = None
    ops.attach_to_province(game.table, card, province)
    _announce_entering_play(game, card.id, request.invest_amount, request.proclaim)


def _announce_entering_play(
    game: GameState, card_id: str, invest_amount: int, proclaim: bool
) -> None:
    """The tail every recruited card shares: make the board legal, queue the post-entry steps, and
    announce the arrival."""
    # A card reaching the battlefield can make the board illegal, and the board is made legal
    # before anything is told the card arrived — a trigger that reads a state the rules say cannot
    # exist is deciding on a board that never legally existed.
    triggers.enforce_state_based_actions(game)
    # Defer the post-entry steps so an enter-play trait that pauses for a choice resolves first.
    game.stack.append(FinishRecruit(card_id, invest_amount, proclaim))
    triggers.fire(game, EnteredPlay(card_id))


def finish_recruit(
    game: GameState, card_id: str, invest_amount: int | None, proclaim: bool = False
) -> None:
    card = game.table.cards_by_id[card_id]
    _clear_sincerity(game, card)
    if proclaim:
        game.use_once(proclaim_key(card.owner, game.turn))
        ops.set_honor(game.table, card.owner, delta=effective_personal_honor(game, card))
    finish_invest(game, card, invest_amount)


def _clear_sincerity(game: GameState, card: L5RCard) -> None:
    """Remove a card's Sincerity tokens once it has entered play — its trait has already read them
    during the ``EnteredPlay`` cascade (Sincerity keyword)."""
    held = card.counters.get(SINCERITY.key, 0)
    if held:
        card.adjust_counter(SINCERITY.key, -held)
