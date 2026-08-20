from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import abilities
from yasuki_core.engine.rules.decisions import ChoosePayment
from yasuki_core.engine.rules.economy import effective_gold_production
from yasuki_core.engine.rules.legality import gold_producers
from yasuki_core.engine.rules.state import GameState


def payment_request(game: GameState, seat: PlayerId, amount: int, label: str) -> ChoosePayment:
    """Build the payment that raises ``amount`` gold from ``seat``, for a cost that prices no card.

    Every unbowed producer the seat controls is offered, quoted at what it makes for nobody in
    particular, along with the boost each one may take as it bows. The pool the seat already holds
    counts toward the cost before anything bows. A Recruit and an Equip build their own payment
    instead: those price a card, and a producer's yield can depend on the card it pays for.

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
    """
    producers = gold_producers(game, seat)
    return ChoosePayment(
        seat=seat,
        candidates=tuple(producer.id for producer in producers),
        amount=amount,
        available=game.gold[seat],
        produced=tuple(
            (producer.id, effective_gold_production(game, producer)) for producer in producers
        ),
        label=label,
        boostable=tuple(
            (producer.id, boost.amount)
            for producer in producers
            if (boost := abilities.production_boost_for(producer)) is not None
        ),
    )


def can_raise(game: GameState, seat: PlayerId, amount: int) -> bool:
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
