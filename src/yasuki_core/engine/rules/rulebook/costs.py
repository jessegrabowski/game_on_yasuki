from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.decisions import ChoosePayment
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.engine.rules.gold.payment import payment_request
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.work import ApplyEffects


def announce_rulebook_cost(
    game: GameState, seat: PlayerId, amount: int, label: str, effects: tuple[Effect, ...]
) -> ChoosePayment:
    """Queue ``effects`` behind a gold cost that no card stands behind, and build the payment.

    A rulebook ability charges the player rather than pricing a card, so the payment carries no
    target and every producer is quoted at what it makes for nobody in particular.
    """
    game.stack.append(ApplyEffects(effects))
    return payment_request(game, seat, amount, label)
