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

    @property
    def cancellable(self) -> bool:
        """Whether the seat may back out of this decision, undoing the action that raised it. False
        for a forced decision the seat must answer."""
        return False


@dataclass(frozen=True, slots=True)
class ChoosePayment(DecisionRequest):
    """The seat must cover a gold cost, bowing gold producers to make up what its pool lacks. The
    candidates are the seat's unbowed producers; choosing some bows them, and their production plus
    the pool must reach the cost. Excess stays in the pool.

    The request snapshots everything :meth:`accepts` needs, so validity is structural: the cost, the
    pool on hand when the cost arose, and each producer's yield.

    Attributes
    ----------
    amount : int
        The gold cost to cover.
    available : int
        The gold already in the seat's pool when the cost arose.
    produced : tuple of (str, int)
        Each candidate producer paired with the gold it yields when bowed.
    label : str
        What the payment is for (e.g. the recruited card's name), shown in the prompt.
    """

    amount: int
    available: int
    produced: tuple[tuple[str, int], ...]
    label: str

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        distinct = set(chosen)
        if len(distinct) != len(chosen) or not distinct <= set(self.candidates):
            return False
        yields = dict(self.produced)
        return self.available + sum(yields[card_id] for card_id in distinct) >= self.amount

    @property
    def cancellable(self) -> bool:
        """A Recruit's payment can be backed out of: nothing is committed until it is answered."""
        return True


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


def _chooses_exactly_one(request: "DecisionRequest", response: DecisionResponse) -> bool:
    return len(response.choices) == 1 and response.choices[0] in request.candidates


@dataclass(frozen=True, slots=True)
class BanishForLegacy(DecisionRequest):
    """The seat must banish one card from hand to pay for the Legacy ability. The candidates are the
    seat's hand; the chosen card is removed from the game. Not cancellable — announcing Legacy
    commits to the cost."""

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseLegacyCard(DecisionRequest):
    """The seat must choose which Legacy card its search found — the candidates are the Legacy cards
    in its dynasty deck and provinces. The chosen card is placed into a province next."""

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseInvestAmount(DecisionRequest):
    """The seat must choose how much to Invest while recruiting a variable-Invest holding. The
    candidates are the affordable amounts rendered as strings; the chosen amount is added to the
    recruit payment and drives the Invest effect. Cancellable — nothing is committed until the
    payment that follows.

    Attributes
    ----------
    source_card_id : str
        The holding being recruited with Invest.
    """

    source_card_id: str

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ChooseAbilityTarget(DecisionRequest):
    """The seat must choose the target of an activated ability it has announced. The candidates are
    the cards the ability may legally target — all in play, so a client renders them as board
    selections.

    Attributes
    ----------
    source_card_id : str
        The card whose ability is resolving, whose effects apply to the chosen target.
    """

    source_card_id: str

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseCards(DecisionRequest):
    """The seat must choose between ``minimum`` and ``maximum`` of the candidate cards — a
    variable-count target, as when a triggered effect targets "zero to two" cards. The chosen ids
    feed the named resolver, whose effects apply once the choice is made. The candidates are the
    cards the effect may legally target, all in play, so a client renders them as board selections.

    Attributes
    ----------
    minimum : int
        The fewest cards the seat may choose — zero when the effect is optional.
    maximum : int
        The most cards the seat may choose.
    resolver : str
        The registered choice resolver that turns the chosen ids into effects.
    source_id : str
        The card whose effect raised the choice, passed to the resolver.
    """

    minimum: int
    maximum: int
    resolver: str
    source_id: str

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        distinct = set(chosen)
        return (
            len(distinct) == len(chosen)
            and self.minimum <= len(chosen) <= self.maximum
            and distinct <= set(self.candidates)
        )


@dataclass(frozen=True, slots=True)
class PlaceLegacy(DecisionRequest):
    """The seat must choose which province to place the found Legacy card into, discarding the card
    already there. The candidates are the province cards eligible to be displaced.

    Attributes
    ----------
    legacy_card_id : str
        The Legacy card that will be placed face-up into the chosen province.
    """

    legacy_card_id: str

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)
