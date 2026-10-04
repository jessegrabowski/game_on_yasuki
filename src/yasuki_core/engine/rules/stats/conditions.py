from collections.abc import Callable

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.vocabulary.modifiers import Condition
from yasuki_core.engine.table import location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import PersonalityPrint


def _attacking(game: GameState, card: L5RCard) -> bool:
    return game.attack is not None and _in_the_army_of(game, card, game.attack.attacker)


def _defending(game: GameState, card: L5RCard) -> bool:
    return game.attack is not None and _in_the_army_of(game, card, game.attack.defender)


def _in_the_army_of(game: GameState, card: L5RCard, seat: PlayerId) -> bool:
    """Whether ``card`` is a Personality ``seat`` controls at the battlefield now being fought."""
    attack = game.attack
    if attack is None or attack.current is None or card.owner is not seat:
        return False
    if not isinstance(card.printed, PersonalityPrint):
        return False
    return location_of(game.table, card).battlefield == attack.current


_CONDITIONS: dict[Condition, Callable[[GameState, L5RCard], bool]] = {
    Condition.ATTACKING: _attacking,
    Condition.DEFENDING: _defending,
}


def condition_holds(game: GameState, card: L5RCard, condition: Condition) -> bool:
    """Whether ``card`` meets ``condition`` right now, read off the board."""
    return _CONDITIONS[condition](game, card)
