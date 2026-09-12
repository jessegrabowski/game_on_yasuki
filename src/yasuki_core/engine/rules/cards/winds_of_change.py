from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.rulebook.favor_payment import favor_payer
from yasuki_core.engine.rules.rulebook.lobby import lobby_bar
from yasuki_core.engine.rules.abilities.idioms import register_event_entry
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.effects import Discard, Effect
from yasuki_core.engine.rules.state import GameState
from yasuki_core.game_pieces.cards import L5RCard


# --- Commanding Favor ---


@favor_payer("commanding_favor")
def _commanding_favor_favor_payer(game: GameState, card: L5RCard) -> list[Effect] | None:
    """ "Interrupt: Discard this Event from play to pay the action's :favor: cost."

    Implemented as a payer priced at discarding itself rather than as the printed Interrupt. The
    printed timing cannot be honored: costs are paid at step B of the Action Sequence and Interrupts
    are played at D. It pays the cost outright rather than substituting for a discard, so it is
    offered to a seat that holds no Favor at all.
    """
    return [Discard(card.id, card.owner)]


register_event_entry("commanding_favor", timing=ActionTiming.DYNASTY)


# --- Miya Shoin ---


@lobby_bar("miya_shoin")
def _miya_shoin_lobby_bar(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
    """ "Other players may not Lobby": everyone but his controller. The ability he grants them to
    take control of him has no handler yet."""
    return seat is not card.owner
