from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId


class VictoryRule(Enum):
    """A way the game can be won or lost, named so a seat can be held to it or excused from it.

    Which of these apply is per seat, not per game: cards excuse one player and not another. The
    Hidden Catacombs of the Scorpion reads "You will not lose, or be eliminated, by Dishonor",
    Kaede Sensei "You permanently will not win an Honor Victory", and A Quest Abandoned takes an
    Enlightenment Victory away from each player who declines its offer.
    :attr:`~yasuki_core.engine.rules.state.GameState.active_rules` holds that per-seat state.

    Names what the engine enforces, not the rulebook's full list. A member is added along with
    the rule that reads it.
    """

    MILITARY_LOSS = "military_loss"
    DISHONOR_LOSS = "dishonor_loss"
    HONOR_VICTORY = "honor_victory"


@dataclass(frozen=True, slots=True)
class GameLost:
    """A seat lost the game. ``reason`` is worded for a player."""

    seat: PlayerId
    reason: str


@dataclass(frozen=True, slots=True)
class GameWon:
    """A seat won the game. ``reason`` names what it won, worded for a player."""

    seat: PlayerId
    reason: str
