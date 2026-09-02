from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChoosePayment
from yasuki_core.engine.rules.effects import Ask, Effect
from yasuki_core.engine.rules.economy import (
    effective_gold_production,
    maximum_gold_production,
    untaken_self_grant,
)
from yasuki_core.engine.rules.legality import gold_producers, reachable_gold
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import TriggerContext
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


def can_afford(
    game: GameState, seat: PlayerId, amount: int, *, bowed_by_cost: frozenset[str] = frozenset()
) -> bool:
    """Whether ``seat`` could cover ``amount``: its pool plus the most every unbowed producer it
    controls could make. Answered before a payment is offered, so an ability whose gold cost the seat
    cannot meet is never announced.

    Parameters
    ----------
    bowed_by_cost : frozenset of str, optional
        Producers this same cost bows, which cannot also bow to produce for it. Default empty.
    """
    return (
        game.gold[seat]
        + sum(
            maximum_gold_production(game, producer)
            for producer in gold_producers(game, seat)
            if producer.id not in bowed_by_cost
        )
        >= amount
    )


def refusal_would_strand(game: GameState, seat: PlayerId, extra: int) -> bool:
    """Whether declining ``extra`` gold leaves the payment ``seat`` is in the middle of unable to
    reach its cost.

    Affordability counts what a producer can grant itself, so a seat offered a purchase only that
    grant reaches has committed to taking it by announcing the purchase. Declining is then not a way
    out and cancelling is, which the question says by refusing no as an answer.

    Parameters
    ----------
    game : GameState
        The live game the pool and the producers are read from.
    seat : PlayerId
        The seat being asked.
    extra : int
        The gold the seat is being offered and could refuse.
    """
    owed = payment_in_flight(game, seat)
    if owed is None:
        return False
    target = game.table.cards_by_id.get(owed.target_id)
    return reachable_gold(game, seat, target) - extra < owed.amount


def payment_in_flight(game: GameState, seat: PlayerId) -> ContinuePayment | None:
    """The cost ``seat`` is part way through covering, or None when it owes nothing.

    The innermost one, since a cost paid to resolve an ability can itself be interrupted."""
    return next(
        (
            item
            for item in reversed(game.stack)
            if isinstance(item, ContinuePayment) and item.seat is seat
        ),
        None,
    )


def offer_self_grant(ctx: TriggerContext, question: str, resolver: str) -> list[Effect]:
    """The offer a card makes in the window it opens as it bows: ``question``, answered by
    ``resolver``, for the card whose window is firing.

    How much is on offer comes from the same projection affordability counts, so the two cannot
    disagree — a window offering less than affordability promised would strand the purchase it made
    reachable. Offers nothing when the event names another card, or when this one has nothing left
    to give this turn.

    Parameters
    ----------
    ctx : TriggerContext
        The firing trigger's context, whose card is the producer being asked about.
    question : str
        The offer as the seat reads it, naming what taking it costs.
    resolver : str
        The registered choice resolver that grants the Gold and charges the card's own price.
    """
    offered = untaken_self_grant(ctx.game, ctx.card)
    if ctx.event.card_id != ctx.card.id or not offered:
        return []
    return [
        Ask(
            ctx.card.owner,
            question,
            resolver,
            (ctx.card.id,),
            source_id=ctx.card.id,
            declinable=not refusal_would_strand(ctx.game, ctx.card.owner, offered),
        )
    ]
