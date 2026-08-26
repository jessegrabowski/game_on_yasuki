from enum import Enum


class VictoryRule(Enum):
    """A way the game can be won or lost, named so a seat can be held to it or excused from it.

    Which of these apply is per seat rather than per game: cards excuse one player and not another.
    The Hidden Catacombs of the Scorpion reads "You will not lose, or be eliminated, by Dishonor",
    Kaede Sensei "You permanently will not win an Honor Victory", and A Quest Abandoned takes an
    Enlightenment Victory away from each player who declines its offer — one game, different rules
    per seat. :attr:`~yasuki_core.engine.rules.state.GameState.active_rules` is where that lives.

    A member is added along with the rule that reads it, so this names what the engine enforces
    rather than the rulebook's full list.
    """

    MILITARY_LOSS = "military_loss"
