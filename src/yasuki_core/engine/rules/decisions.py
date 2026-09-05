from abc import ABC, abstractmethod
from dataclasses import dataclass

from yasuki_core.engine.players import PlayerId


@dataclass(frozen=True, slots=True)
class DecisionResponse:
    """A seat's answer to the pending :class:`DecisionRequest`.

    Carries the chosen identifiers — card ids, gold-source ids, or an ordering — interpreted by
    the request being answered. One uniform shape so the decision log, the save format, and the
    netcode all serialize answers the same way. A request whose answer needs a second dimension
    subclasses this rather than widening it, so a mechanic only one decision reads stays off the
    type every decision shares.

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

    @abstractmethod
    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        """The question to put to the seat. ``partial`` is the answer as it stands, for a request
        whose wording tracks the selection being made; the rest ignore it."""

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

    An answer names one producer, and the payment comes back round for whatever is still owed. That
    is what lets a producer's own trait pause to ask its controller a question as it bows: with two
    producers in one answer, the second one's question would overwrite the first's.

    The request snapshots what it quotes for: the cost, the pool on hand when the cost arose, and
    each producer's yield. :meth:`accepts` asks whether the cost is still *reachable* after the
    answer rather than whether the answer already covers it — an answer that leaves the cost out of
    reach is refused, because it would strand the payment with the board already changed.

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
    grantable : tuple of (str, int)
        Each producer that can still raise its own yield this turn, paired with the extra Gold it
        would add. What it costs and how it asks are the card's business, settled in the window it
        opens as it bows; only the figure is here, because reachability cannot be judged without it.
    """

    amount: int
    available: int
    produced: tuple[tuple[str, int], ...]
    label: str
    target_id: str = ""
    grantable: tuple[tuple[str, int], ...] = ()

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return f"Pay {self.shortfall(partial)} gold for {self.label}"

    def shortfall(self, partial: DecisionResponse = DecisionResponse()) -> int:
        """The gold still owed once every producer ``partial`` names has bowed for what it makes
        right now. What the seat reads as it picks, so a producer that can raise its own yield
        counts at the lower figure until its window has actually granted it."""
        yields = dict(self.produced)
        covered = self.available + sum(yields[card_id] for card_id in partial.choices)
        return max(0, self.amount - covered)

    def covers_cost(self, partial: DecisionResponse) -> bool:
        """Whether the producers ``partial`` names meet the cost between them, counting what each
        can still grant itself in the window it opens as it bows.

        What a client asks to decide whether the seat has picked enough to finish. It differs from
        :meth:`accepts`, which judges one answer the engine is actually sent: a seat picks its whole
        payment at once and the engine bows one producer per answer, so the two count different
        sets."""
        grants = dict(self.grantable)
        return self.shortfall(partial) <= sum(grants.get(card_id, 0) for card_id in partial.choices)

    @property
    def confirm_label(self) -> str:
        return "Pay"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        if len(chosen) > 1:
            return False  # one producer per answer; the payment comes back round for the rest
        distinct = set(chosen)
        if not distinct <= set(self.candidates):
            return False
        # Bowing nothing is an answer only when the pool already covers the cost; otherwise it makes
        # no progress, and a payment that accepted it would ask the same question forever.
        if not distinct and self.available < self.amount:
            return False
        # Reachability against this request's own snapshot, so a client can refuse the answer before
        # sending it. `flow._continue_payment` asks the live board, and is the authority when they
        # disagree — an answer can change what another producer is worth.
        #
        # Every producer counts at its ceiling, the one being bowed included: it is asked for its own
        # grant in the window it opens, so naming it does not decide against that grant.
        ceiling = sum(made for _, made in self.produced) + sum(extra for _, extra in self.grantable)
        return self.available + ceiling >= self.amount

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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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
    resolver_context : tuple of str, optional
        What an earlier step of the same choice settled, handed to the resolver alongside the
        answer — a resolver is otherwise given only what was picked. Default empty.
    """

    question: str
    resolver: str
    source_id: str
    resolver_context: tuple[str, ...] = ()

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    """

    source_card_id: str
    ability_key: str | None = None

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
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


ASSIGNMENT_SEPARATOR = "@"


def assignment_token(card_id: str, battlefield: int) -> str:
    """The candidate string pairing the Personality ``card_id`` with the battlefield at index
    ``battlefield`` — how :class:`AssignUnits` names one place a unit could go."""
    return f"{card_id}{ASSIGNMENT_SEPARATOR}{battlefield}"


def assignment(token: str) -> tuple[str, int]:
    """The Personality and battlefield index :func:`assignment_token` encoded.

    Returns
    -------
    card_id : str
        The Personality leading the assigned unit.
    battlefield : int
        Where it goes, indexing the attack's battlefields.

    Raises
    ------
    ValueError
        If ``token`` names neither.
    """
    card_id, separator, index = token.rpartition(ASSIGNMENT_SEPARATOR)
    if not separator or not card_id or not index.isdigit():
        raise ValueError(f"not an assignment token: {token!r}")
    return card_id, int(index)


@dataclass(frozen=True, slots=True)
class AssignUnits(DecisionRequest):
    """The seat must assign any number of its unbowed Personalities from home to battlefields.

    A candidate pairs a unit with a battlefield rather than naming either alone, because assigning is
    a choice of *where* and one Personality may go to any battlefield the attack made. Read a choice
    through :func:`assignment` rather than splitting the string. The whole seat answers at once: the
    CR has each seat assign simultaneously, so this is one request per seat rather than one per unit.

    Assigning nothing is a well-formed answer — the CR lets a seat keep some or all of its
    Personalities at home.

    Attributes
    ----------
    battlefields : int
        How many battlefields the attack created, which the candidates index into.
    """

    battlefields: int

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return f"Assign units to battlefields ({len(partial.choices)} assigned)"

    @property
    def confirm_label(self) -> str:
        return "Assign"

    def accepts(self, response: DecisionResponse) -> bool:
        if not set(response.choices) <= set(self.candidates):
            return False
        # A unit stands at one battlefield. Two tokens for the same Personality is not a richer
        # answer than one, it is a contradiction, and picking either would be arbitrary.
        assigned = [assignment(token)[0] for token in response.choices]
        return len(set(assigned)) == len(assigned)


@dataclass(frozen=True, slots=True)
class ChooseBattlefield(DecisionRequest):
    """The Attacker must choose where the next battle is fought.

    The candidates are the indices of the battlefields no battle has been fought at yet, as strings.
    Exactly one battle happens at each, so the choice is the order rather than the set.
    """

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a battlefield to fight at"

    @property
    def confirm_label(self) -> str:
        return "Fight"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseFortificationProvince(DecisionRequest):
    """The seat must choose which of its Provinces a Fortification attaches to.

    Raised only when the card was brought into play from somewhere other than a Province, which the
    CR gives its controller the choice for. The candidates are zone tokens rather than card ids: a
    Province is a slot, and an empty one takes a Fortification as readily as an occupied one.

    Attributes
    ----------
    source_card_id : str
        The Fortification, already on the battlefield and waiting to be attached.
    invest_amount : int
        The Invest cost paid for it, applied once it has entered play.
    proclaim : bool
        Whether the recruit was a Proclaim.
    """

    source_card_id: str
    invest_amount: int = 0
    proclaim: bool = False

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a Province for the Fortification"

    @property
    def confirm_label(self) -> str:
        return "Attach"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


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
    declinable : bool, optional
        Whether no is an answer. False when refusing would strand something the seat is already
        committed to, which leaves cancelling as its only way out rather than declining. Default
        True.
    """

    question: str
    resolver: str
    source_id: str | None = None
    declinable: bool = True

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return self.question

    def accepts(self, response: DecisionResponse) -> bool:
        if not response.choices:
            return self.declinable
        return response.choices == self.candidates

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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        registered = CHOICE_PROMPTS.get(self.resolver)
        if registered is not None:
            return registered
        cards = "card" if self.maximum == 1 else "cards"
        if self.minimum == 0:
            return f"Choose up to {self.maximum} {cards}"
        if self.minimum == self.maximum:
            return f"Choose {self.minimum} {cards}"
        return f"Choose {self.minimum} to {self.maximum} {cards}"

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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        wording = CHOICE_PROMPTS.get(self.resolver, "Divide them among one or more cards")
        return f"{wording} ({self.count - len(partial.choices)} of {self.count} left)"

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

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a province to place the Legacy card, discarding the card there"

    @property
    def confirm_label(self) -> str:
        return "Place"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseLobbyTarget(DecisionRequest):
    """The seat must choose which Personality its Lobby bows. The candidates are its own unbowed
    Personalities with 1 or more Personal Honor, so a client renders them as board selections."""

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a Personality to bow for the Imperial Favor"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseInheritanceTarget(DecisionRequest):
    """The seat must choose which Holding its Inheritance ability raises. The candidates are the
    Holdings it controls in play, so a client renders them as board selections."""

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a Holding to give +3 Gold Production"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it."""
        return True
