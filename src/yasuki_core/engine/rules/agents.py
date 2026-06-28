from typing import Protocol

from yasuki_core.engine.rules.decisions import DecisionRequest, DecisionResponse
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
    it leans on the request's own ``accepts`` rather than knowing the decision type."""

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        for size in range(len(request.candidates) + 1):
            response = DecisionResponse(request.candidates[:size])
            if request.accepts(response):
                return response
        raise ValueError(f"no auto-answer satisfies {type(request).__name__}")
