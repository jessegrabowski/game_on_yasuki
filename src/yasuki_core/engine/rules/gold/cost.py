from yasuki_core.engine.rules.vocabulary.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.engine.table import unit_members
from yasuki_core.game_pieces.cards import L5RCard


def unit_gold_cost(game: GameState, personality: L5RCard) -> int:
    """A unit's total Gold Cost: the Personality's own and every card attached to him (CR, Unit).

    What a card means by "his unit's cost": the pool a variable-cost action is priced against.
    """
    return sum(
        effective_gold_cost(game, member) for member in unit_members(game.table, personality)
    )


def effective_gold_cost(game: GameState, card: L5RCard) -> int:
    """What ``card`` costs before the seat's own discounts and surcharges: its printed gold cost
    plus every active Gold Cost modifier on it, floored at zero. A card printing no gold cost has
    none to modify, so it stays at zero (CR, Absent Stats).

    Parameters
    ----------
    game : GameState
        The live game the modifiers are read from.
    card : L5RCard
        The card being priced.

    Returns
    -------
    cost : int
        The modified gold cost.
    """
    return effective_stat(game, card, Stat.GOLD_COST)
