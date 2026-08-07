from typing import Protocol

from yasuki_core.engine.rules.decisions import (
    ChoosePayment,
    DecisionRequest,
    DecisionResponse,
)
from yasuki_core.engine.rules.projection import GameView


class Agent(Protocol):
    """Answers a :class:`DecisionRequest` with a :class:`DecisionResponse`.

    The human UI, the AI, a network peer, and test doubles are all Agents, so the engine never cares
    who answers a decision (KD3). A bot answers synchronously here; the human UI instead presents
    the request and submits the answer through the session when the player acts."""

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse: ...


class AutoAgent:
    """A placeholder bot standing in for the AI: answers any request with the shortest prefix of its
    candidates that the request accepts (the whole list for an ordering). Generic by construction —
    it leans on the request's own ``accepts`` rather than knowing the decision type.

    That generality has one hole: a prefix of candidates cannot express a bow-time production boost,
    so a cost only reachable by boosting has no answer here. :class:`PayingAgent` covers it."""

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        for size in range(len(request.candidates) + 1):
            response = DecisionResponse(request.candidates[:size])
            if request.accepts(response):
                return response
        raise ValueError(f"no auto-answer satisfies {type(request).__name__}")


class PayingAgent:
    """Covers a gold cost by bowing producers, and answers everything else like :class:`AutoAgent`.

    Bows the smallest producers first, so the largest stay straight for a second purchase in the
    same turn. This is a greedy rule rather than a search for the cheapest covering set — a cost of
    4 met from yields of 1, 2 and 5 bows all three here.

    A boost is a last resort. Taking one grants the producer extra Gold Production for the turn at
    whatever price its card names — Outlying Farms destroys itself — so it is used only when the
    plain production of every producer still falls short. That matters because
    :meth:`~yasuki_core.engine.session.EngineSession.legal_actions` offers a recruit whose cost only
    a boost can reach, which an agent that could not boost would be unable to pay for at all.
    """

    def __init__(self) -> None:
        self._fallback = AutoAgent()

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChoosePayment):
            return self._pay(request)
        return self._fallback.decide(request, view)

    @staticmethod
    def _pay(request: ChoosePayment) -> DecisionResponse:
        shortfall = request.amount - request.available
        if shortfall <= 0:
            return DecisionResponse(())
        bowed: list[str] = []
        raised = 0
        for producer, yields in sorted(request.produced, key=lambda pair: pair[1]):
            if raised >= shortfall:
                break
            bowed.append(producer)
            raised += yields
        boost = dict(request.boostable)
        boosted: list[str] = []
        for producer in bowed:
            if raised >= shortfall:
                break
            if producer in boost:
                boosted.append(producer)
                raised += boost[producer]
        return DecisionResponse(tuple(bowed), tuple(boosted))
