from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import triggers
from yasuki_core.engine.rules.effects import AdjustHonorChange, Discard
from yasuki_core.engine.rules.state import GameState


def honor_interrupt(game: GameState, card_id: str, seat: PlayerId, delta: int) -> None:
    """Take the Honor rulebook Interrupt: discard ``card_id`` from the acting seat's hand to change
    the size of ``seat``'s next Honor gain or loss in the interrupted action by ``delta``. Claims
    the acting seat's one use against this action."""
    acting = game.round.priority
    game.honor_interrupted.add(acting)
    triggers.resolve_effects(game, [Discard(card_id, acting), AdjustHonorChange(seat, delta)])
