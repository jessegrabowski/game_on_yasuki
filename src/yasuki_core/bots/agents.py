from typing import Protocol, runtime_checkable

from yasuki_core.engine.rules.vocabulary.decisions import (
    BanishForLegacy,
    ChooseDistribution,
    ChooseLegacyCard,
    ChoosePayment,
    Confirm,
    DecisionRequest,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.gold.self_grants import is_production_window
from yasuki_core.engine.redaction import CardView, HiddenCard
from yasuki_core.engine.rules.projection import GameView


@runtime_checkable
class Agent(Protocol):
    """Answers a :class:`~.DecisionRequest` with a :class:`~.DecisionResponse`.

    The human UI, the AI, a network peer, and test doubles are all Agents, so the engine never cares
    who answers a decision (KD3). A bot answers synchronously here. The human UI instead presents
    the request and submits the answer through the session when the player acts.

    Attributes
    ----------
    name : str
        How this agent is reported. A run is characterized by its policy and its agent together, so
        naming only one of them describes half of what produced the numbers.
    """

    name: str

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse: ...


class AutoAgent:
    """A placeholder bot standing in for the AI: answers any request with the shortest prefix of its
    candidates that the request accepts (the whole list for an ordering). Generic by construction,
    it leans on the request's own ``accepts`` rather than knowing the decision type.

    One answer a prefix of distinct candidates cannot express is handled rather than left to fail: a
    division names one candidate several times, and is answered here by heaping the whole of it onto
    the first."""

    name = "auto"

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChooseDistribution):
            return DecisionResponse(request.candidates[:1] * request.count)
        for size in range(len(request.candidates) + 1):
            response = DecisionResponse(request.candidates[:size])
            if request.accepts(response):
                return response
        raise ValueError(f"no auto-answer satisfies {type(request).__name__}")


class PayingAgent:
    """Covers a gold cost by bowing producers, and answers everything else like
    :class:`~.AutoAgent`.

    Bows the smallest producer first, leaving the largest straight for a later purchase the same
    turn, and answers again each time the payment comes back round. Greedy, not a search for the
    cheapest covering set: a cost of 4 met from yields of 1, 2 and 5 bows all three.

    Takes a producer's own grant only when every producer's plain yield still falls short, since
    raising a yield can cost the producer itself (Outlying Farms destroys itself). That decision is
    made while answering the payment, before the later window that offers the grant one producer at
    a time opens. That window carries no figures of its own, so the shortfall is only visible while
    answering the payment. A window that refuses no overrides it: the seat committed to the grant by
    announcing the purchase, so there is nothing left to weigh.

    Taking a grant matters because ``EngineSession.legal_actions`` can offer a recruit whose cost
    only a grant can reach, which an agent that always declined would be unable to pay for.
    """

    name = "paying"

    def __init__(self) -> None:
        self._fallback = AutoAgent()
        self._needs_a_grant = False

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChoosePayment):
            return self._pay(request)
        if isinstance(request, Confirm) and is_production_window(request, view.table.battlefield):
            declined = DecisionResponse()
            if self._needs_a_grant or not request.accepts(declined):
                return DecisionResponse(request.candidates)
            return declined
        return self._fallback.decide(request, view)

    def _pay(self, request: ChoosePayment) -> DecisionResponse:
        plain = sum(made for _, made in request.produced)
        self._needs_a_grant = request.available + plain < request.amount
        if request.amount <= request.available:
            return DecisionResponse(())
        producer, _ = min(request.produced, key=lambda pair: pair[1])
        return DecisionResponse((producer,))


class LegacyAgent:
    """Answers the Legacy decisions for economic value, and everything else like
    :class:`~.PayingAgent`.

    Takes the biggest producer the search found, and displaces the province card worth least, both
    ranked on printed Gold Production, the only figure a card outside play carries. Whether the
    trade is worth making at all is the policy's call, not this agent's.

    The banished hand card is chosen by id. A policy that never plays from hand loses nothing by it,
    and pretending otherwise would invent a valuation this model does not have.
    """

    name = "legacy"

    def __init__(self) -> None:
        self._fallback = PayingAgent()

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        match request:
            case ChooseLegacyCard():
                return DecisionResponse((_richest(request.candidates, view),))
            case PlaceLegacy():
                return DecisionResponse((_poorest(request.candidates, view),))
            case BanishForLegacy():
                return DecisionResponse((min(request.candidates),))
        return self._fallback.decide(request, view)


AGENTS: dict[str, type[Agent]] = {
    agent.name: agent for agent in (AutoAgent, PayingAgent, LegacyAgent)
}
"""Every agent a run can be configured with, by name."""


def make_agent(name: str) -> Agent:
    """Build the agent registered under ``name``.

    Raises
    ------
    KeyError
        If no agent is registered under ``name``, listing those that are.
    """
    if name not in AGENTS:
        raise KeyError(f"unknown agent {name!r}; known: {', '.join(sorted(AGENTS))}")
    return AGENTS[name]()


def _identified(candidates: tuple[str, ...], view: GameView) -> dict[str, CardView]:
    """The candidate cards the viewer can identify, by id. One it cannot is omitted rather than
    guessed at, and ranks as producing nothing."""
    wanted = set(candidates)
    found = {
        card.id: card
        for zone in view.table.zones.values()
        for card in zone.cards
        if not isinstance(card, HiddenCard) and card.id in wanted
    }
    found.update({card.id: card for card in view.legacy_pool if card.id in wanted})
    return found


def _richest(candidates: tuple[str, ...], view: GameView) -> str:
    """The candidate to take: most Gold Production, then least Gold Cost, then lowest id.

    Cheapest breaks the tie because the card still has to be paid for once it is placed, so between
    equal producers the affordable one is likelier to reach play the turn it arrives.
    """
    known = _identified(candidates, view)

    def rank(card_id: str) -> tuple[int, int, str]:
        production, cost = _economics(known.get(card_id))
        return -production, cost, card_id

    return min(candidates, key=rank)


def _poorest(candidates: tuple[str, ...], view: GameView) -> str:
    """The candidate to give up: least Gold Production, then most Gold Cost, then lowest id."""
    known = _identified(candidates, view)

    def rank(card_id: str) -> tuple[int, int, str]:
        production, cost = _economics(known.get(card_id))
        return production, -cost, card_id

    return min(candidates, key=rank)


def _economics(card: CardView | None) -> tuple[int, int]:
    """A card's printed Gold Production and Gold Cost, both 0 when it carries neither or is None."""
    return getattr(card, "gold_production", 0) or 0, getattr(card, "gold_cost", 0) or 0
