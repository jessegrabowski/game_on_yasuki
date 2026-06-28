from abc import ABC, abstractmethod
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId


@dataclass(frozen=True, slots=True)
class DecisionResponse:
    """A seat's answer to the pending :class:`DecisionRequest`.

    Carries the chosen identifiers — card ids, gold-source ids, or an ordering — interpreted by
    the request being answered. One uniform shape so the decision log, the save format, and the
    netcode all serialize answers the same way.

    Attributes
    ----------
    choices : tuple of str
        The chosen identifiers, in the order the seat picked them. Default empty.
    """

    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionRequest(ABC):
    """A question the engine pauses to put to one seat.

    The engine runs until it needs input, records a concrete request on ``GameState.pending``, and
    returns; the seat answers with a :class:`DecisionResponse` and the engine resumes. Concrete
    requests form a closed union that grows with the rules vocabulary.

    Attributes
    ----------
    seat : PlayerId
        The seat that must answer.
    candidates : tuple of str
        The ids the seat may choose among — the request's legal options. A client renders these as
        the selectable cards, and a well-formed answer draws only from them.
    """

    seat: PlayerId
    candidates: tuple[str, ...]

    @abstractmethod
    def accepts(self, response: DecisionResponse) -> bool:
        """Return whether ``response`` is a structurally well-formed answer to this request — the
        right shape, drawn from :attr:`candidates`. A well-formed answer may still be illegal
        against the game state; the rules layer makes that check separately."""


@dataclass(frozen=True, slots=True)
class DiscardToHandSize(DecisionRequest):
    """The seat must discard ``count`` cards from hand to reach the maximum hand size, taken at the
    end of its turn. The candidates are the seat's current hand.

    Attributes
    ----------
    count : int
        How many cards the seat must discard.
    """

    count: int

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = set(response.choices)
        return (
            len(response.choices) == self.count
            and len(chosen) == self.count
            and chosen <= set(self.candidates)
        )
