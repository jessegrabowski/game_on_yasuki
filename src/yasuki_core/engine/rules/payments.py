from collections.abc import Iterable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.rules.decisions import BoostOffer, ChoosePayment
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.legality import gold_producers
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


def boost_offers_for(producers: Iterable[L5RCard]) -> tuple[BoostOffer, ...]:
    """The bow-time boosts ``producers`` offer, for the payment that will quote them."""
    return tuple(
        BoostOffer(producer.id, boost.amount, boost.price)
        for producer in producers
        if (boost := abilities.production_boost_for(producer)) is not None
    )


def payment_request(
    game: GameState,
    seat: PlayerId,
    amount: int,
    label: str,
    target: L5RCard | None = None,
) -> ChoosePayment:
    """Queue the payment's completion and build the first request for ``amount`` gold from ``seat``.

    Every unbowed producer the seat controls is offered, quoted at what it makes for ``target``,
    along with the boost each may take as it bows. The pool the seat already holds counts toward the
    cost before anything bows.

    Parameters
    ----------
    game : GameState
        The live game the producers and the pool are read from.
    seat : PlayerId
        The seat being charged.
    amount : int
        The gold to raise.
    label : str
        What the payment is for, shown in the prompt.
    target : L5RCard, optional
        The card being paid for, for a producer whose yield depends on what it pays for. Omit for a
        rulebook cost, which prices no card. Default None.
    """
    producers = gold_producers(game, seat)
    targets = () if target is None else (target,)
    target_id = "" if target is None else target.id
    return ChoosePayment(
        seat=seat,
        candidates=tuple(producer.id for producer in producers),
        amount=amount,
        available=game.gold[seat],
        produced=tuple(
            (producer.id, effective_gold_production(game, producer, targets=targets))
            for producer in producers
        ),
        label=label,
        target_id=target_id,
        boostable=boost_offers_for(producers),
    )


def can_afford(game: GameState, seat: PlayerId, amount: int) -> bool:
    """Whether ``seat`` could cover ``amount``: its pool plus everything its unbowed producers make,
    boosts included. Answered before a payment is offered, so an ability whose gold cost the seat
    cannot meet is never announced."""
    total = game.gold[seat]
    for producer in gold_producers(game, seat):
        total += effective_gold_production(game, producer)
        boost = abilities.production_boost_for(producer)
        if boost is not None:
            total += boost.amount
    return total >= amount
