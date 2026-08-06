import random
from typing import Protocol

from yasuki_core.engine.rules.actions import Action, Pass, Recruit
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.table import ZoneRole
from yasuki_core.game_pieces.dynasty import DynastyCard, DynastyHolding


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


class EconomicPolicy:
    """Buys the best economy on offer, and passes when there is nothing to buy.

    Ranks the plain Recruits by the province card's Gold Production first and its Gold Cost second,
    so the bigger producer wins and cost only breaks a tie between equals. Ties beyond that go to
    the lowest card id, which keeps a run reproducible rather than dependent on zone ordering.

    Affordability is never rechecked: :meth:`~yasuki_core.engine.session.EngineSession.legal_actions`
    withholds a recruit the seat cannot reach, so a policy deciding for itself would drift from the
    engine and offer choices the driver then refuses.

    Two things it deliberately does not weigh. Invest and Proclaim variants are skipped, because each
    changes what the payment has to answer without serving the economic aim. And the ranking reads
    the card's printed cost, which is what a view carries — a card whose cost a discount lowers is
    ranked as though it cost full price.

    This models a fixed player rather than a good one. The harness compares decks under one
    policy, which makes the policy a control variable: tuning it leaves runs from either side of
    the change incomparable.
    """

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        purchases = [
            action
            for action in actions
            if isinstance(action, Recruit) and not action.invest and not action.proclaim
        ]
        if not purchases:
            return next((action for action in actions if isinstance(action, Pass)), actions[0])
        cards = _readable_province_cards(view)
        return min(purchases, key=lambda purchase: _rank(cards[purchase.card_id]))


def _rank(card: DynastyCard) -> tuple[int, int, str]:
    """How a province card sorts for purchase, lowest first.

    Gold Production leads and Gold Cost breaks the tie, both negated so the larger wins. The card id
    settles anything still level, so the choice does not follow zone order.
    """
    production = card.gold_production if isinstance(card, DynastyHolding) else 0
    cost = 0 if card.gold_cost is None else card.gold_cost
    return -production, -cost, card.id


def _readable_province_cards(view: GameView) -> dict[str, DynastyCard]:
    """The viewer's province cards it can identify, by id — what a Recruit's ``card_id`` refers to.

    Built by scanning rather than looked up, since a redacted view carries no id index. A province
    that refilled face-down reaches even its owner as a :class:`HiddenCard`, which no Recruit can
    name, so those are skipped rather than ranked.
    """
    return {
        card.id: card
        for key, zone in view.table.zones.items()
        if key.owner is view.viewer and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if not isinstance(card, HiddenCard)
    }
