from abc import ABC, abstractmethod
from collections.abc import Sequence
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
    boosted : tuple of str
        The subset of ``choices`` whose bow-time production boost the seat took — a boostable
        producer raised to its higher yield as it bows, then destroyed. Only meaningful answering a
        :class:`ChoosePayment`. Default empty.
    """

    choices: tuple[str, ...] = ()
    boosted: tuple[str, ...] = ()


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

    @abstractmethod
    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        """The question to put to the seat. ``chosen`` and ``boosted`` are the selections made so
        far, for a request whose wording depends on them; the rest ignore both."""

    @property
    def confirm_label(self) -> str:
        """The confirm button's text. Requests answered another way never read it."""
        return "Confirm"

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
    target_id : str
        The card being paid for. Resolution recomputes each producer's yield against it, because a
        producer's yield can depend on what it pays for.
    boostable : tuple of (str, int)
        Each producer that may raise its yield as it bows, paired with the extra gold its boost
        would add. The seat opts in per producer via the answer's ``boosted``; taking a boost grants
        the producer that much Gold Production for the turn, and costs whatever its card says.
    """

    amount: int
    available: int
    produced: tuple[tuple[str, int], ...]
    label: str
    target_id: str = ""
    boostable: tuple[tuple[str, int], ...] = ()

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        yields = dict(self.produced)
        boost = dict(self.boostable)
        boosted_set = set(boosted)
        covered = self.available + sum(
            yields[card_id] + (boost[card_id] if card_id in boosted_set else 0)
            for card_id in chosen
        )
        return f"Pay {max(0, self.amount - covered)} gold for {self.label}"

    @property
    def confirm_label(self) -> str:
        return "Pay"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        distinct = set(chosen)
        if len(distinct) != len(chosen) or not distinct <= set(self.candidates):
            return False
        boost = dict(self.boostable)
        boosted = set(response.boosted)
        if not boosted <= (distinct & boost.keys()):
            return False
        yields = dict(self.produced)
        covered = sum(yields[c] + (boost[c] if c in boosted else 0) for c in distinct)
        return self.available + covered >= self.amount

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

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return f"discard {self.count} card(s)"

    @property
    def confirm_label(self) -> str:
        return "Discard"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = set(response.choices)
        return (
            len(response.choices) == self.count
            and len(chosen) == self.count
            and chosen <= set(self.candidates)
        )


@dataclass(frozen=True, slots=True)
class LeaveBowed(DecisionRequest):
    """The seat must say which of its bowed cards to keep bowed as its turn begins.

    "May remain bowed" is a choice its controller makes before each straightening rather than a
    standing exemption (CR, May Remain Bowed), so the turn start asks. The candidates are the cards
    offering it; those chosen stay bowed and the rest straighten with everything else.
    """

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose cards to leave bowed"

    @property
    def confirm_label(self) -> str:
        return "Leave bowed"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = set(response.choices)
        return len(chosen) == len(response.choices) and chosen <= set(self.candidates)

    @property
    def cancellable(self) -> bool:
        """The turn beginning is not an action to back out of."""
        return False


def _chooses_exactly_one(request: "DecisionRequest", response: DecisionResponse) -> bool:
    return len(response.choices) == 1 and response.choices[0] in request.candidates


@dataclass(frozen=True, slots=True)
class BanishForLegacy(DecisionRequest):
    """The seat must banish one card from hand to pay for the Legacy ability. The candidates are the
    seat's hand; the chosen card is removed from the game. Not cancellable — announcing Legacy
    commits to the cost."""

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Banish a card from hand to search for a Legacy card"

    @property
    def confirm_label(self) -> str:
        return "Banish"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseLegacyCard(DecisionRequest):
    """The seat must choose which Legacy card its search found — the candidates are the Legacy cards
    in its dynasty deck and provinces. The chosen card is placed into a province next."""

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Search your deck for a Legacy card"

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

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose how much to Invest"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ChooseAmount(DecisionRequest):
    """The seat must say how much Gold to spend on an action whose cost block prints a variable
    amount — the ``:X:`` whose effects scale with what is paid (CR, Costs).

    The candidates are the amounts the seat could pay, rendered as strings; the answer feeds the
    named resolver, which prices the payment and shapes what the amount bought. A client shows a
    number, not a board selection.

    Attributes
    ----------
    question : str
        What the amount is for, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen amount is handed to.
    source_id : str
        The card charging the cost, handed to the resolver as its context.
    """

    question: str
    resolver: str
    source_id: str

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return self.question

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the action; nothing is paid until the amount is settled."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseOption(DecisionRequest):
    """The seat must pick one of the outcomes an ability spells out — the "gain or lose", "this
    player or that" a card leaves to the player rather than reading off the board.

    The candidates are the outcomes as the seat reads them; the answer feeds the named resolver,
    which turns the chosen label back into effects. A client shows a list of wordings, not a board
    selection and not a number.

    Attributes
    ----------
    question : str
        What is being chosen, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen option is handed to.
    source_id : str
        The card offering the choice, handed to the resolver as its context.
    """

    question: str
    resolver: str
    source_id: str

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return self.question

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the action: the choice is the whole of what it does."""
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

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose a target for the ability"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseEquipTarget(DecisionRequest):
    """The seat must choose which Personality the attachment it is Equipping joins. The candidates
    are the Personalities it controls that will accept the card, all in play, so a client renders
    them as board selections.

    Attributes
    ----------
    source_card_id : str
        The attachment being Equipped, still in hand until the cost is paid.
    invest_amount : int or None
        The Invest cost being paid alongside the Gold Cost, or None when the Equip takes no Invest.
        A free Invest is an amount of zero, not None.
    """

    source_card_id: str
    invest_amount: int | None = None

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose a Personality to equip"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out abandons the Equip before anything is paid."""
        return True


# Resolver key -> the wording its choice asks with. Populated by the choice_resolver decorator and
# read here rather than in triggers, because a prompt is only ever a property of the request the
# seat sees, and decisions sits below triggers in the import order.
CHOICE_PROMPTS: dict[str, str] = {}


@dataclass(frozen=True, slots=True)
class Confirm(DecisionRequest):
    """The seat must answer a yes/no question naming what it is being asked to do.

    An optional effect whose subject is already settled — "destroy this Farm to straighten the card
    it recruited" — reads as a question rather than as a card selection. Answering yes returns the
    candidates, answering no returns none, so this is an optional :class:`ChooseCards` in every
    respect but how a client puts it: a question with two buttons instead of a board selection.

    Attributes
    ----------
    question : str
        The question as the seat reads it, naming the cards it concerns.
    resolver : str
        The registered choice resolver that turns the answer into effects.
    source_id : str, optional
        A card id handed to the resolver as its context, as for :class:`ChooseCards`. Default None.
    """

    question: str
    resolver: str
    source_id: str | None = None

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return self.question

    def accepts(self, response: DecisionResponse) -> bool:
        return response.choices in ((), self.candidates)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True


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
    source_id : str, optional
        A card id handed to the resolver as its context. Which card that is belongs to the resolver
        — often the one whose trigger raised the choice, sometimes the card being acted on. None
        when the rulebook raises the choice and there is no card to name. Default None.
    """

    minimum: int
    maximum: int
    resolver: str
    source_id: str | None = None

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        registered = CHOICE_PROMPTS.get(self.resolver)
        if registered is not None:
            return registered
        if self.minimum == 0:
            return f"Choose up to {self.maximum} card(s)"
        return f"Choose {self.minimum} to {self.maximum} card(s)"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        distinct = set(chosen)
        return (
            len(distinct) == len(chosen)
            and self.minimum <= len(chosen) <= self.maximum
            and distinct <= set(self.candidates)
        )

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseDistribution(DecisionRequest):
    """The seat must divide ``count`` identical creations among one or more of the candidates — the
    "create N Followers and attach them to one or more of your Personalities" a card hands to its
    controller rather than reading off the board.

    The answer names a candidate once per creation it takes, so an id appearing twice takes two and
    one left out takes none. That keeps the answer the tuple of ids every other decision carries,
    and it says "one or more" without a second count: a card getting nothing is simply not named.

    Attributes
    ----------
    count : int
        How many creations there are to divide. All of them are placed — the seat chooses where
        they go, not whether they arrive.
    resolver : str
        The registered choice resolver that turns the division into effects.
    source_id : str
        The card dividing them, handed to the resolver as its context.
    """

    count: int
    resolver: str
    source_id: str

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        wording = CHOICE_PROMPTS.get(self.resolver, "Divide them among one or more cards")
        return f"{wording} ({self.count - len(chosen)} of {self.count} left)"

    def accepts(self, response: DecisionResponse) -> bool:
        return len(response.choices) == self.count and set(response.choices) <= set(self.candidates)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True


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

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose a province to place the Legacy card, discarding the card there"

    @property
    def confirm_label(self) -> str:
        return "Place"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseInheritanceTarget(DecisionRequest):
    """The seat must choose which Holding its Inheritance ability raises. The candidates are the
    Holdings it controls in play, so a client renders them as board selections."""

    def prompt(self, chosen: Sequence[str] = (), boosted: Sequence[str] = ()) -> str:
        return "Choose a Holding to give +3 Gold Production"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it."""
        return True
