from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.board.queries import has_keyword
from yasuki_core.engine.rules.effects import AdjustHonorChange, Discard, Effect, GainHonor
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseHonorInterrupt,
    DecisionResponse,
    honor_interrupt,
    honor_interrupt_token,
)
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard

# An Honor Interrupt makes a gain or loss one larger or one smaller.
HONOR_INTERRUPT_DELTAS = (1, -1)


def honor_cards_in_hand(game: GameState, seat: PlayerId) -> list[L5RCard]:
    """The Honor cards ``seat`` holds, which the Honor Interrupt discards."""
    hand = game.table.zones[ZoneKey(seat, ZoneRole.HAND)]
    return [card for card in hand.cards if has_keyword(game, card, keywords.HONOR)]


def interrupters(game: GameState, gain: GainHonor) -> list[PlayerId]:
    """The seats still to be offered the Honor Interrupt against ``gain``, the active player first
    (ShE datasheet, Interrupt).

    Nobody for a change that says it is not interruptible, nobody outside an action, since there
    is nothing to interrupt, and nobody during a Response Step, since a Response is not
    interruptible. A change of zero is not a gain or loss (CR, Honor
    Gains and Losses). A seat is offered each change once, and may take the Interrupt once per
    action. "Inside an action" means ``game.action`` is set, which also reaches a change a
    triggered trait raised during the action, a wider window than the datasheet's "the action's
    Honor gains or losses".
    """
    if not gain.interruptible or game.action is None or gain.amount == 0:
        return []
    if game.round.kind is RoundKind.RESPONSE:
        return []
    order = [game.active, *(seat for seat in game.table.seats if seat is not game.active)]
    return [
        seat
        for seat in order
        if seat not in gain.asked
        and seat not in game.honor_interrupted
        and honor_cards_in_hand(game, seat)
    ]


def honor_interrupt_request(game: GameState, gain: GainHonor) -> ChooseHonorInterrupt:
    """The Interrupt offered to the first seat :func:`~.interrupters` names against ``gain``."""
    seat = interrupters(game, gain)[0]
    candidates = tuple(
        honor_interrupt_token(card.id, delta)
        for card in honor_cards_in_hand(game, seat)
        for delta in HONOR_INTERRUPT_DELTAS
    )
    return ChooseHonorInterrupt(
        seat=seat,
        candidates=candidates,
        honor_seat=gain.seat,
        amount=gain.amount,
        asked=gain.asked,
    )


def apply_honor_interrupt(
    game: GameState, request: ChooseHonorInterrupt, response: DecisionResponse
) -> None:
    """Resume the change ``request`` guarded with the seat's answer spliced in ahead of it: the
    discard and the adjustment when it interrupted, and in either case the change itself, which
    asks the next seat or performs once every seat has answered.

    The discard runs inside the interrupted action's cascade, so a reaction to it fires and it
    joins the action's event record: a Response asking what the action discarded sees it.

    Raise ``RuntimeError`` if the card named is no longer an Honor card in the seat's hand.
    """
    produced: list[Effect] = []
    if response.choices:
        card_id, delta = honor_interrupt(response.choices[0])
        if card_id not in {card.id for card in honor_cards_in_hand(game, request.seat)}:
            raise RuntimeError(
                f"{card_id} is no longer an Honor card in {request.seat.name}'s hand"
            )
        produced = [
            Discard(card_id, request.seat),
            AdjustHonorChange(request.honor_seat, delta, by=request.seat),
        ]
    produced.append(
        GainHonor(request.honor_seat, request.amount, asked=request.asked | {request.seat})
    )
    triggers.resume_paused_cascade(game, produced)
