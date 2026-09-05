from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities import (
    favor_payer,
    lobby_bar,
    register_event_entry,
)
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.effects import Discard, Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Commanding Favor ---


@favor_payer("commanding_favor")
def _commanding_favor_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Interrupt: Discard this Event from play to pay the action's :favor: cost."

    It pays the cost outright rather than substituting for a discard, so it is offered to a seat
    that holds no Favor at all. Implemented as a payer priced at discarding itself rather than as
    the Interrupt it prints: a cost is paid at step B of the Action Sequence and an Interrupt is
    played at D, so the printed window opens after the cost it names.

    """
    return [Discard(card.id, card.owner)]


register_event_entry("commanding_favor", timing=ActionTiming.DYNASTY)


# --- Miya Shoin ---


@lobby_bar("miya_shoin")
def _miya_shoin_lobby_bar(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
    """ "Other players may not Lobby" — everyone but his controller. The ability he grants them to
    take control of him has no handler yet."""
    return seat is not card.owner
