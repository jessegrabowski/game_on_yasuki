from yasuki_core.engine.rules.abilities import favor_payer
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

    Its other line, "Dynasty: Put this Event into play", has no handler yet.
    """
    return [Discard(card.id, card.owner)]
