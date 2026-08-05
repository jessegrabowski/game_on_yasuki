import random
from typing import Protocol

from yasuki_core.engine.rules.actions import Action, Pass
from yasuki_core.engine.rules.projection import GameView


class Policy(Protocol):
    """Chooses which action a seat takes from the ones open to it.

    The counterpart to :class:`~yasuki_core.engine.rules.agents.Agent`: a policy picks an action, an
    agent answers a decision that action raises. A Recruit needs both — the policy chooses to
    recruit, the agent answers the payment.

    Policies read the seat's :class:`GameView` rather than the game itself, so one cannot see the
    opponent's hand and works unchanged over a network. The view carries live card objects, so a
    policy weighing a card's Gold Production or Gold Cost has them to hand.
    """

    def choose(self, view: GameView, actions: list[Action]) -> Action: ...


class PassPolicy:
    """Passes whenever it can. The baseline a metric is validated against: a game played this way
    barely changes, so its numbers are checkable by hand."""

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next((action for action in actions if isinstance(action, Pass)), actions[0])


class RandomPolicy:
    """Picks uniformly among the offered actions.

    Takes its own :class:`random.Random` rather than reaching for the module-level one, so two runs
    of the same simulation with the same seed play the same game.
    """

    def __init__(self, rng: random.Random):
        self._rng = rng

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return self._rng.choice(actions)
