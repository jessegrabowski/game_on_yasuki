from yasuki_core.engine.rules.rulebook.dynasty_discard import is_dynasty_discard
from yasuki_core.engine.rules.vocabulary.actions import (
    Action,
    ActivateAbility,
    Pass,
    Recruit,
)
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
        return next((a for a in actions if is_dynasty_discard(a)), Pass())


class RecruitElseDiscard:
    """Buys what it can afford and throws away what it cannot, so a turn does both."""

    name = "recruit-else-discard"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next(
            (a for a in actions if isinstance(a, Recruit)),
            next((a for a in actions if is_dynasty_discard(a)), Pass()),
        )


class Cheater:
    """Chooses an action it was never offered, so a driver's refusal can be tested: an ability on a
    card no table holds."""

    name = "cheater"
    action = ActivateAbility("never-dealt")

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return self.action
