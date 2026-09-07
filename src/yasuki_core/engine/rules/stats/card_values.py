from yasuki_core.engine.rules.modifiers import Stat
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.stats.calculation import effective_stat
from yasuki_core.game_pieces.cards import L5RCard


def effective_force(game: GameState, card: L5RCard) -> int:
    """``card``'s Force right now, counters and granted modifiers included."""
    return effective_stat(game, card, Stat.FORCE)


def effective_chi(game: GameState, card: L5RCard) -> int:
    """``card``'s Chi right now, counters and granted modifiers included. Zero is a meaningful
    answer for a Personality rather than merely a floor: the Chi Death Rule destroys one whose Chi
    is ever zero."""
    return effective_stat(game, card, Stat.CHI)


def effective_personal_honor(game: GameState, card: L5RCard) -> int:
    """``card``'s Personal Honor right now — what Proclaiming him gains, and what an effect reading
    his honor sees. The +1PH and +2PH counters carry their delta here."""
    return effective_stat(game, card, Stat.PERSONAL_HONOR)


def effective_weapon_limit(game: GameState, card: L5RCard) -> int:
    """How many Weapon Items may be attached to ``card`` (CR, Weapon). One by default, two for a
    Kensai, and whatever a card's own modifiers make it."""
    return effective_stat(game, card, Stat.WEAPON_LIMIT)
