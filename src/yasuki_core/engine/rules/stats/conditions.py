from collections.abc import Callable

from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import Condition
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


def _attacking(game: GameState, card: L5RCard) -> bool:
    attack = game.attack
    if attack is None or attack.current is None or card.owner is not attack.attacker:
        return False
    if not isinstance(card.printed, PersonalityPrint):
        return False
    return location_of(game.table, card).battlefield == attack.current


_CONDITIONS: dict[Condition, Callable[[GameState, L5RCard], bool]] = {
    Condition.ATTACKING: _attacking,
}


def condition_holds(game: GameState, card: L5RCard, condition: Condition) -> bool:
    """Whether ``card`` meets ``condition`` right now, read off the board."""
    return _CONDITIONS[condition](game, card)
