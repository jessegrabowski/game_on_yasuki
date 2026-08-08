from collections.abc import Iterable
from typing import Protocol

from numpy.random import Generator, default_rng

from yasuki_core.engine.rules.actions import Action, Cycle, Legacy, Pass, Recruit
from yasuki_core.engine.redaction import HiddenCard
from yasuki_core.engine.rules.agents import PayingAgent
from yasuki_core.engine.rules.decisions import ChooseCards, DecisionRequest, DecisionResponse
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

    Attributes
    ----------
    name : str
        How this policy is reported. A simulation's numbers describe a deck *under a policy*, so a
        result quoted without one cannot be compared against anything.
    """

    name: str

    def choose(self, view: GameView, actions: list[Action]) -> Action: ...


class PassPolicy:
    """Passes whenever it can. The baseline a metric is validated against: a game played this way
    barely changes, so its numbers are checkable by hand."""

    name = "pass"

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return next((action for action in actions if isinstance(action, Pass)), actions[0])


class RandomPolicy:
    """Picks uniformly among the offered actions.

    Takes its own :class:`numpy.random.Generator` rather than reaching for a module-level one, so
    two runs of the same simulation with the same seed play the same game. Built without one it
    seeds itself, which is fine for a smoke run and useless for a reproducible one.
    """

    name = "random"

    def __init__(self, rng: Generator | None = None):
        self._rng = default_rng() if rng is None else rng

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        return actions[int(self._rng.integers(len(actions)))]


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

    name = "economic"

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


class EconomicLegacyPolicy:
    """Buys like :class:`EconomicPolicy`, and takes the Legacy ability when it improves the board.

    Legacy banishes a card from hand to search the seat's dynasty deck and face-down provinces for a
    Legacy card, then places it face-up over a province card, discarding what was there. It is worth
    taking only when the best producer it could find beats the best one already face-up in its own
    provinces — otherwise it spends two cards to reach production the seat could simply buy.

    Finding nothing loses the game outright, so an empty ``legacy_pool`` is a hard veto rather than a
    weighing.

    Two simplifications it makes, both of which flatter the ability. It ranks on printed Gold
    Production, since a card not yet in play has no effective value to read. And it treats the
    banished hand card as free, which it is under this policy — nothing here ever plays from hand.
    """

    name = "economic-legacy"

    def __init__(self) -> None:
        self._buying = EconomicPolicy()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        legacy = next((action for action in actions if isinstance(action, Legacy)), None)
        if legacy is not None and self._worth_taking(view):
            return legacy
        return self._buying.choose(view, actions)

    @staticmethod
    def _worth_taking(view: GameView) -> bool:
        """Whether the pool holds a better producer than any already face-up in the seat's
        provinces. Affordability is not weighed: what a seat can pay for shifts within the turn as
        it bows producers, while what sits in its provinces does not."""
        if not view.legacy_pool:
            # Unreachable while the comparison below is strict, since an empty pool produces 0 and
            # no board produces less. Kept because loosening that comparison would otherwise turn
            # an empty pool into a lost game.
            return False
        return _best_production(view.legacy_pool) > _best_production(
            _readable_province_cards(view).values()
        )


def cards_to_cycle(view: GameView) -> tuple[str, ...]:
    """The face-up Province cards worth putting on the bottom of the deck, by id.

    A card is worth replacing when it produces less Gold than a card drawn off the deck would on
    average, the deck being exactly the distribution a redraw samples from. A card with no Gold
    Production stat — a Personality — counts as producing nothing, so an economic seat replaces it
    whenever its deck produces at all.

    Returns empty when the deck is empty — a redraw would hand the same cards straight back — or
    when every face-up card already beats what the deck offers.
    """
    deck = view.dynasty_deck
    if not deck:
        return ()
    average = sum(_production(card) for card in deck) / len(deck)
    return tuple(
        sorted(
            card_id
            for card_id, card in _readable_province_cards(view).items()
            # Identifiable is not the same as face-up: a seat peeking its own face-down Province
            # cards can read one Cycle would refuse to be given.
            if card.face_up and _production(card) < average
        )
    )


class EconomicCyclePolicy:
    """Buys like :class:`EconomicPolicy`, and cycles an opening that its deck can beat.

    Cycle is a first-turn-only rulebook ability: put one or more face-up Province cards on the
    bottom of the dynasty deck, refill, and reveal. It is taken when :func:`cards_to_cycle` finds
    anything worth replacing.

    Answers its own Cycle decision as well as choosing it, so the cards put back are the ones the
    choice was made over. Every other decision falls through to :class:`PayingAgent`.
    """

    name = "economic-cycle"

    def __init__(self) -> None:
        self._buying = EconomicPolicy()
        self._answering = PayingAgent()

    def choose(self, view: GameView, actions: list[Action]) -> Action:
        cycle = next((action for action in actions if isinstance(action, Cycle)), None)
        if cycle is not None and cards_to_cycle(view):
            return cycle
        return self._buying.choose(view, actions)

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChooseCards) and request.resolver == "cycle":
            return DecisionResponse(cards_to_cycle(view))
        return self._answering.decide(request, view)


POLICIES: dict[str, type[Policy]] = {
    policy.name: policy
    for policy in (
        PassPolicy,
        RandomPolicy,
        EconomicPolicy,
        EconomicLegacyPolicy,
        EconomicCyclePolicy,
    )
}
"""Every policy a run can be configured with, by name."""


def make_policy(name: str) -> Policy:
    """Build the policy registered under ``name``.

    A stochastic policy seeds itself here; construct it directly with the run's
    :class:`numpy.random.Generator` when the run has to be reproducible.

    Raises
    ------
    KeyError
        If no policy is registered under ``name``, listing those that are.
    """
    if name not in POLICIES:
        raise KeyError(f"unknown policy {name!r}; known: {', '.join(sorted(POLICIES))}")
    return POLICIES[name]()


def _rank(card: DynastyCard) -> tuple[int, int, str]:
    """How a province card sorts for purchase, lowest first.

    Gold Production leads and Gold Cost breaks the tie, both negated so the larger wins. The card id
    settles anything still level, so the choice does not follow zone order.
    """
    production = _production(card)
    cost = 0 if card.gold_cost is None else card.gold_cost
    return -production, -cost, card.id


def _readable_province_cards(view: GameView) -> dict[str, DynastyCard]:
    """The viewer's province cards it can identify, by id — what a Recruit's ``card_id`` refers to.

    Built by scanning rather than looked up, since a redacted view carries no id index. A card the
    viewer cannot identify — a province refilled face-down, until something reveals it — is skipped
    rather than ranked, since no Recruit can name it.
    """
    return {
        card.id: card
        for key, zone in view.table.zones.items()
        if key.owner is view.viewer and key.role is ZoneRole.PROVINCE
        for card in zone.cards
        if not isinstance(card, HiddenCard)
    }


def _best_production(cards: Iterable[DynastyCard]) -> int:
    """The largest printed Gold Production among ``cards``, or 0 when none of them produces."""
    return max((_production(card) for card in cards), default=0)


def _production(card: DynastyCard) -> int:
    return card.gold_production if isinstance(card, DynastyHolding) else 0
