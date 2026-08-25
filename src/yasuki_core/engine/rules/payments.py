from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChoosePayment
from yasuki_core.engine.rules.economy import (
    effective_gold_production,
    maximum_gold_production,
    untaken_self_grant,
)
from yasuki_core.engine.rules.legality import gold_producers
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.work import ContinuePayment
from yasuki_core.game_pieces.cards import L5RCard


def payment_request(
    game: GameState,
    seat: PlayerId,
    amount: int,
    label: str,
    target: L5RCard | None = None,
) -> ChoosePayment:
    """Queue the payment's completion and build the first request for ``amount`` gold from ``seat``.

    Every unbowed producer the seat controls is offered, quoted at what it makes for ``target`` right
    now. A producer whose own trait can raise that quotes the lower figure and asks in its window as
    it bows, so the answer the seat gives here is only which card to bow. The pool the seat already
    holds counts toward the cost before anything bows.

    The completion is pushed onto the stack before the request is raised, so it sits above whatever
    the announcing action queued and resolves first — bowing what the answer names, then re-raising
    for the remainder or spending once the pool covers the cost.

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
    game.stack.append(ContinuePayment(seat, amount, label, target_id))
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
        grantable=tuple(
            (producer.id, extra)
            for producer in producers
            if (extra := untaken_self_grant(game, producer))
        ),
    )


def can_afford(game: GameState, seat: PlayerId, amount: int) -> bool:
    """Whether ``seat`` could cover ``amount``: its pool plus the most every unbowed producer it
    controls could make. Answered before a payment is offered, so an ability whose gold cost the seat
    cannot meet is never announced."""
    return (
        game.gold[seat]
        + sum(maximum_gold_production(game, producer) for producer in gold_producers(game, seat))
        >= amount
    )
