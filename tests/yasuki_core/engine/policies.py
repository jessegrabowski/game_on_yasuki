from yasuki_core.engine.rules.actions import Action, DynastyDiscard, Legacy, Pass, Recruit
from yasuki_core.engine.rules.projection import GameView


class RecruitFirst:
    """Recruits whenever a Recruit is offered, and passes otherwise."""

    name = "recruit-first"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next((a for a in actions if isinstance(a, Recruit)), Pass())


class DiscardFirst:
    """Discards from a province whenever it can, and passes otherwise."""

    name = "discard-first"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next((a for a in actions if isinstance(a, DynastyDiscard)), Pass())


class RecruitElseDiscard:
    """Buys what it can afford and throws away what it cannot, so a turn does both."""

    name = "recruit-else-discard"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next(
            (a for a in actions if isinstance(a, Recruit)),
            next((a for a in actions if isinstance(a, DynastyDiscard)), Pass()),
        )


class Cheater:
    """Chooses an action it was never offered, so a driver's refusal can be tested."""

    name = "cheater"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return Legacy() if Legacy() not in actions else Pass()
