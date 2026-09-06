from typing import Protocol, runtime_checkable

from yasuki_core.engine.rules.decisions import (
    BanishForLegacy,
    ChooseDistribution,
    ChooseLegacyCard,
    ChoosePayment,
    Confirm,
    DecisionRequest,
    DecisionResponse,
    PlaceLegacy,
)
from yasuki_core.engine.rules.economy import GOLD_SELF_GRANT
from yasuki_core.engine.redaction import CardView, HiddenCard
from yasuki_core.engine.rules.projection import GameView


@runtime_checkable
class Agent(Protocol):
    """Answers a :class:`DecisionRequest` with a :class:`DecisionResponse`.

    The human UI, the AI, a network peer, and test doubles are all Agents, so the engine never cares
    who answers a decision (KD3). A bot answers synchronously here; the human UI instead presents
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
    candidates that the request accepts (the whole list for an ordering). Generic by construction —
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
    """Covers a gold cost by bowing producers, and answers everything else like :class:`AutoAgent`.

    Bows the smallest producer first, so the largest stay straight for a second purchase in the same
    turn, and answers again each time the payment comes back round. This is a greedy rule rather
    than a search for the cheapest covering set — a cost of 4 met from yields of 1, 2 and 5 bows all
    three.

    A producer's own grant is a last resort. Raising a yield costs whatever the card names — Outlying
    Farms destroys itself — so the offer is taken only when what every producer plainly makes still
    falls short. That matters because
    :meth:`~yasuki_core.engine.session.EngineSession.legal_actions` offers a recruit whose cost only
    a grant can reach, which an agent that always declined would be unable to pay for at all.

    Whether to take one is settled while answering the payment, since that is where the shortfall is
    visible; the window that asks for it opens later, one producer at a time, and carries no figures
    of its own. A window that refuses no overrides that judgment — the seat committed to the grant by
    announcing the purchase, so there is nothing left to weigh.
    """

    name = "paying"

    def __init__(self) -> None:
        self._fallback = AutoAgent()
        self._needs_a_grant = False

    def decide(self, request: DecisionRequest, view: GameView) -> DecisionResponse:
        if isinstance(request, ChoosePayment):
            return self._pay(request)
        if isinstance(request, Confirm) and is_production_window(request, view):
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


def is_production_window(request: Confirm, view: GameView) -> bool:
    """Whether a yes/no question is a producer's bow-time window rather than some other card's.

    Recognized by the card asking, not by the resolver: every card that can raise its own Gold
    Production declares the amount, so the registry is the list of cards whose window this could be.
    """
    if request.source_id is None:
        return False
    return any(
        not isinstance(entry.card, HiddenCard)
        and entry.card.id == request.source_id
        and entry.card.printed_id in GOLD_SELF_GRANT
        for entry in view.table.battlefield
    )


class LegacyAgent:
    """Answers the Legacy decisions for economic value, and everything else like
    :class:`PayingAgent`.

    Takes the biggest producer the search found, and displaces the province card worth least, both
    ranked on printed Gold Production — the only figure a card outside play carries. Whether the
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
