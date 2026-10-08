from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from yasuki_core.engine.players import Cause, PlayerId

# The "target" phrases of an action that are already settled, in print order, each holding the ids
# it targeted.
PickedTargets = tuple[tuple[str, ...], ...]


class PickLimit(Protocol):
    """A condition one phrase puts on the cards chosen together, beyond how many of them there are:
    "one or two of your target cards in one unit", "with total Force less than Zaiberu's".

    A limit answers three questions, because they come apart. :meth:`permits` says whether a card
    may still join what is picked, which narrows a board as the seat clicks. :meth:`satisfied` says
    whether what is picked is a legal answer, which lights the confirm. :meth:`admits` says whether
    a set of a given size could satisfy it at all, which is what decides whether the question may
    be asked. A ceiling refuses the pick that would break it, so its first two answers agree. A
    floor refuses nothing and is unsatisfied until enough is picked, so they do not.

    :meth:`describe` answers a fourth, which is not about legality at all: what the prompt should
    say about the answer so far. A limit that is pure arithmetic, such as a running total against
    a bound, holds a figure the seat cannot read off the board, so it says it. A limit the graying
    already shows says nothing.

    An implementation is plain data, read off the board when the question is raised, so that a
    pending request compares equal to the one a replay rebuilds.
    """

    def permits(self, picked: tuple[str, ...], candidate: str) -> bool:
        """Whether ``candidate`` may join ``picked``."""
        ...

    def satisfied(self, picked: tuple[str, ...]) -> bool:
        """Whether ``picked`` meets this limit as it stands."""
        ...

    def admits(self, candidates: tuple[str, ...], count: int) -> bool:
        """Whether some ``count`` of ``candidates`` satisfies this limit."""
        ...

    def describe(self, picked: tuple[str, ...]) -> str:
        """Where ``picked`` stands against this limit, for the prompt to carry, or the empty string
        from a limit with nothing to add to what the board already shows."""
        ...


def within_reach(candidates: Iterable[str], limits: tuple[PickLimit, ...]) -> tuple[str, ...]:
    """Those of ``candidates`` a legal answer could hold at all: the ones every limit permits as a
    first pick. A card whose own Force already breaks a total the set may not exceed is no legal
    target even alone, so offering it would ask a question with no legal answer."""
    return tuple(
        candidate
        for candidate in candidates
        if all(limit.permits((), candidate) for limit in limits)
    )


def answerable(candidates: tuple[str, ...], minimum: int, limits: tuple[PickLimit, ...]) -> bool:
    """Whether a question offering ``candidates`` and asking for at least ``minimum`` of them has a
    legal answer: enough cards to pick from, and every limit able to seat that many of them. A
    phrase asking for two cards whose total Force must stay under five has none to ask for among
    three Personalities of Force three each.

    Each limit is asked separately, so with more than one the answer is necessary but not
    sufficient: two limits can each seat ``minimum`` cards over sets that do not overlap. No card
    carries two yet, and the one that does should be read against a joint check rather than this.
    """
    return len(candidates) >= minimum and all(limit.admits(candidates, minimum) for limit in limits)


@dataclass(frozen=True, slots=True)
class OneGroup:
    """Every pick comes from one part of ``groups``: the "in one unit" Ring of Air prints, and
    the same wording about one Province or one location. The first pick is free and settles which
    part the rest come from, and taking it back opens the choice up again.

    A part of one card is how "a target Personality, or any number of target attachments" says
    that its first half takes exactly one. Picking that card leaves its part with nothing else in
    it, so no second card may join it.

    Attributes
    ----------
    groups : tuple of tuple of str
        A partition of the candidates. A candidate in no part is in no legal answer at all, so it
        is never offered.
    """

    groups: tuple[tuple[str, ...], ...]

    def permits(self, picked: tuple[str, ...], candidate: str) -> bool:
        return self.satisfied((*picked, candidate))

    def satisfied(self, picked: tuple[str, ...]) -> bool:
        chosen = set(picked)
        return any(chosen.issubset(group) for group in self.groups)

    def admits(self, candidates: tuple[str, ...], count: int) -> bool:
        """Whether one part holds ``count`` of ``candidates`` between them."""
        offered = set(candidates)
        return any(len(offered.intersection(group)) >= count for group in self.groups)

    def describe(self, picked: tuple[str, ...]) -> str:
        """Nothing. Which part the first pick settled is what the board stops offering, and the
        part has no name a limit holding only ids could put in a prompt."""
        return ""


@dataclass(frozen=True, slots=True)
class TotalAtMost:
    """The cards chosen together carry at most ``bound`` between them: "one or two target
    Personalities with total Force less than Zaiberu's", "any number of target attachments with
    total Gold cost less than Yamadera's Force".

    Attributes
    ----------
    weights : tuple of (str, int)
        What each candidate contributes, read off the board when the question is raised, so a card
        whose Force changes afterwards does not move the arithmetic under an answer half given. A
        candidate absent from it contributes nothing.
    bound : int
        The most the picks may total. A card reading "less than" passes one less than the figure
        it names.
    unit : str, optional
        The stat's abbreviation as a card writes it, appended to both figures the prompt reports:
        "F", "GC". Default empty, bare numbers.
    """

    weights: tuple[tuple[str, int], ...]
    bound: int
    unit: str = ""

    def total(self, picked: tuple[str, ...]) -> int:
        """What ``picked`` weighs between them."""
        chosen = set(picked)
        return sum(weight for card_id, weight in self.weights if card_id in chosen)

    def permits(self, picked: tuple[str, ...], candidate: str) -> bool:
        return self.satisfied((*picked, candidate))

    def satisfied(self, picked: tuple[str, ...]) -> bool:
        return self.total(picked) <= self.bound

    def admits(self, candidates: tuple[str, ...], count: int) -> bool:
        """Whether the ``count`` lightest of ``candidates`` stay inside the bound, which is the
        most a set of that size can hope for."""
        weights = dict(self.weights)
        cheapest = sorted(weights.get(candidate, 0) for candidate in candidates)
        return sum(cheapest[:count]) <= self.bound

    def describe(self, picked: tuple[str, ...]) -> str:
        """The running total against the bound, or nothing once the answer holds only cards this
        limit does not weigh, which is the half of a :class:`~.OneGroup` phrase its total does not
        govern."""
        weighted = {card_id for card_id, _ in self.weights}
        if picked and weighted.isdisjoint(picked):
            return ""
        return f"Selected {self.total(picked)}{self.unit}/{self.bound}{self.unit}"


@dataclass(frozen=True, slots=True)
class DecisionResponse:
    """A seat's answer to the pending :class:`~.DecisionRequest`.

    Carries the chosen identifiers: card ids, gold-source ids, or an ordering. The request being
    answered interprets them. One uniform shape so the decision log, the save format, and the
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
    returns. The seat answers with a :class:`~.DecisionResponse` and the engine resumes. Concrete
    requests form a closed union that grows with the rules vocabulary.

    Attributes
    ----------
    seat : PlayerId
        The seat that must answer.
    candidates : tuple of str
        The ids the seat may choose among, the request's legal options. A client renders these as
        the selectable cards, and a well-formed answer draws only from them.
    triggered : bool, optional
        Whether a trigger raised the request, reacting to an event already committed. Backing out
        is refused for such a request whatever its ``cancellable`` says, because the event it
        answers cannot be taken back. Keyword-only. Default False.
    limits : tuple of :class:`~.PickLimit`, optional
        The conditions one phrase puts on the cards chosen together, beyond their number, which
        :meth:`selectable` reads to narrow a board as it is answered and :meth:`limit_note` reads
        to word what they leave to say. A request type that carries them enforces them in its own
        ``accepts``. Keyword-only. Default none.
    """

    seat: PlayerId
    candidates: tuple[str, ...]
    triggered: bool = field(default=False, kw_only=True)
    limits: tuple[PickLimit, ...] = field(default=(), kw_only=True)

    def selectable(self, partial: DecisionResponse = DecisionResponse()) -> tuple[str, ...]:
        """The candidates ``partial`` may still grow by: every one for a request under no limit, and
        otherwise those every limit permits joining what is picked. A card already picked stays
        among them, so a client answering with clicks can take it back."""
        if not self.limits:
            return self.candidates
        picked = partial.choices
        return tuple(
            card_id
            for card_id in self.candidates
            if card_id in picked or all(limit.permits(picked, card_id) for limit in self.limits)
        )

    def limit_note(self, partial: DecisionResponse = DecisionResponse()) -> str:
        """What this request's limits have to say about ``partial``, for a prompt to carry
        alongside its own wording. Empty when none of them has anything to add."""
        notes = (limit.describe(partial.choices) for limit in self.limits)
        return ", ".join(note for note in notes if note)

    @abstractmethod
    def accepts(self, response: DecisionResponse) -> bool:
        """Return whether ``response`` is a structurally well-formed answer to this request: the
        right shape, drawn from ``candidates``. A well-formed answer may still be illegal
        against the game state. The rules layer makes that check separately."""

    @abstractmethod
    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        """The question to put to the seat. ``partial`` is the answer as it stands, for a request
        whose wording tracks the selection being made, and the rest ignore it."""

    @property
    def confirm_label(self) -> str:
        """The confirm button's text. Requests answered another way never read it."""
        return "Confirm"

    @property
    def cancellable(self) -> bool:
        """Whether the seat may back out of this decision, undoing the action that raised it. False
        for a forced decision the seat must answer."""
        return False

    @property
    def reopens_on_cancel(self) -> bool:
        """Whether backing out returns to the decision the seat answered just before this one,
        instead of unwinding the action that raised it. True for a later step of an answer whose
        earlier steps changed nothing on the board."""
        return False


@dataclass(frozen=True, slots=True)
class ChoosePayment(DecisionRequest):
    """The seat must cover a gold cost, bowing gold producers to make up what its pool lacks. The
    candidates are the seat's unbowed producers. Choosing some bows them, and their production plus
    the pool must reach the cost. Excess stays in the pool.

    An answer names one producer, and the payment comes back round for whatever is still owed. That
    is what lets a producer's own trait pause to ask its controller a question as it bows: with two
    producers in one answer, the second one's question would overwrite the first's.

    The request snapshots what it quotes for: the cost, the pool on hand when the cost arose, and
    each producer's yield. :meth:`accepts` asks whether the cost is still *reachable* after the
    answer rather than whether the answer already covers it. An answer that leaves the cost out of
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
        opens as it bows. Only the figure is here, because reachability cannot be judged without it.
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
        # disagree, because an answer can change what another producer is worth.
        #
        # Every producer counts at its ceiling, the one being bowed included: it is asked for its
        # own grant in the window it opens, so naming it does not decide against that grant.
        ceiling = sum(made for _, made in self.produced) + sum(extra for _, extra in self.grantable)
        return self.available + ceiling >= self.amount

    @property
    def cancellable(self) -> bool:
        """A Recruit's payment can be backed out of: nothing is committed until it is answered."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseDiscard(DecisionRequest):
    """The seat must choose exactly ``count`` of the candidates, cards in ``holder``'s hand, for
    ``holder`` to discard. The seat is the holder when a card reads "must discard a card" and when
    the hand is over the maximum hand size, and another seat when a card has that seat choose.

    Attributes
    ----------
    count : int
        How many cards are discarded.
    holder : PlayerId
        The seat whose hand the candidates are in.
    cause : PlayerId, Rulebook or Trait
        Who or what the discard belongs to, carried onto each ``CardDiscarded``.
    """

    count: int
    holder: PlayerId
    cause: Cause

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        cards = "card" if self.count == 1 else "cards"
        if self.holder is self.seat:
            return f"Discard {self.count} {cards}"
        return f"Choose {self.count} {cards} for {self.holder.name} to discard"

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
    """The seat must say which of its bowed cards to keep bowed as its turn begins (CR, May
    Remain Bowed).

    The choice is made fresh at each straightening rather than a standing exemption. The
    candidates are the cards offering the choice. Those chosen stay bowed and the rest
    straighten with everything else.
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
class ChooseAmount(DecisionRequest):
    """The seat must name one of the amounts on offer, rendered as strings. A client shows a
    number, not a board selection. The answer is the amount the action declares, and the named
    resolver says what it does.

    Attributes
    ----------
    question : str
        What the amount is for, as the seat reads it.
    resolver : str
        The registered choice resolver the chosen amount is handed to.
    source_id : str
        The card asking, handed to the resolver as its context.
    resolver_context : tuple of str, optional
        What the cost settled before asking, carried through to the resolver. Default empty.
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
        """Backing out unwinds the action. Nothing is paid until the amount is settled."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseOption(DecisionRequest):
    """The seat must pick one of the outcomes an ability spells out, such as "gain or lose" or
    "this player or that", or several of them where the card lets it, as a Strategy's two Invests
    can be paid together.

    The candidates are the outcomes as the seat reads them. The answer feeds the named resolver,
    which turns the chosen label back into effects. A client shows a list of wordings, not a board
    selection and not a number.

    Attributes
    ----------
    question : str
        What is being chosen, as the seat reads it.
    resolver : str or None
        The registered choice resolver the chosen option is handed to, or None where the effect that
        asked takes the answer itself, as an alternate effect does.
    source_id : str
        The card offering the choice, handed to the resolver as its context.
    resolver_context : tuple of str, optional
        What an earlier step of the same choice settled, handed to the resolver alongside the
        answer. A resolver is otherwise given only what was picked. Default empty.
    minimum : int, optional
        The fewest outcomes an answer may pick. Default 1.
    maximum : int, optional
        The most outcomes an answer may pick. Default 1.
    """

    question: str
    resolver: str | None
    source_id: str
    resolver_context: tuple[str, ...] = ()
    minimum: int = 1
    maximum: int = 1

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return self.question

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        return (
            self.minimum <= len(chosen) <= self.maximum
            and len(set(chosen)) == len(chosen)
            and set(chosen) <= set(self.candidates)
        )

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the action: the choice is the whole of what it does."""
        return True


@dataclass(frozen=True, slots=True)
class ChooseAbilityTarget(DecisionRequest):
    """The seat must choose the target of an activated ability it has announced. The candidates are
    the cards the ability may legally target, all in play, so a client renders them as board
    selections.

    Attributes
    ----------
    source_card_id : str
        The card whose ability is resolving, whose effects apply to the chosen target.
    ability_key : str, optional
        Names the ability among the several the card prints, so the one announced is the one
        that resolves. Default None, the card's only ability.
    source_name : str, optional
        The card's name, for the prompt. Default empty, which leaves the card unnamed.
    targeting_message : str, optional
        What the ability targets, as its card words it. Default None, which asks for a card.
    minimum : int, optional
        The fewest distinct targets the seat chooses at once. Default 1.
    maximum : int, optional
        The most, for a card that targets a range of them: "one or two target Personalities with
        total Force less than Zaiberu's". Default 1, one target.
    settled  : tuple of tuple of str, optional
        The ability's earlier "target" phrases and what each of them targeted, in print order, for
        a card printing more than one. The answer to this one is appended to them. Default none,
        the ability's first or only phrase.
    """

    source_card_id: str
    ability_key: str | None = None
    source_name: str = ""
    targeting_message: str | None = None
    minimum: int = 1
    maximum: int = 1
    settled: PickedTargets = ()

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        wanted = self._wanted()
        phrase = f"{self.source_name}: target {wanted}" if self.source_name else f"Target {wanted}"
        note = self.limit_note(partial)
        return f"{phrase} ({note})" if note else phrase

    def _wanted(self) -> str:
        """What the phrase takes, with the count in front of it where it takes more than one."""
        offered = self.targeting_message or ("a card" if self.maximum == 1 else "the cards offered")
        if self.maximum == 1:
            return offered
        if self.minimum == self.maximum:
            return f"{self.minimum} of {offered}"
        if self.maximum == self.minimum + 1:
            return f"{self.minimum} or {self.maximum} of {offered}"
        return f"{self.minimum} to {self.maximum} of {offered}"

    def accepts(self, response: DecisionResponse) -> bool:
        choices = response.choices
        distinct = set(choices)
        return (
            len(distinct) == len(choices)
            and self.minimum <= len(choices) <= self.maximum
            and distinct <= set(self.candidates)
            and all(limit.satisfied(choices) for limit in self.limits)
        )

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True

    @property
    def reopens_on_cancel(self) -> bool:
        """Backing out of a later "target" phrase returns to the one before it. Targeting changes
        nothing on the board, so a seat that has read what its first pick left on offer can take
        that pick back without giving up the action."""
        return bool(self.settled)


@dataclass(frozen=True, slots=True)
class ChooseEquipTarget(DecisionRequest):
    """The seat must choose which Personality the attachment it is Equipping joins. The candidates
    are the Personalities it controls that will accept the card, all in play, so a client renders
    them as board selections.

    Attributes
    ----------
    source_card_id : str
        The attachment being Equipped, still in hand with its cost already paid.
    """

    source_card_id: str

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose a Personality to equip"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole Equip, the cost it paid included."""
        return True


# Resolver key -> the wording its choice asks with. Populated by the choice_resolver decorator and
# read here rather than in triggers, because a prompt is only ever a property of the request the
# seat sees, and decisions sits below triggers in the import order.
CHOICE_PROMPTS: dict[str, str] = {}
# Resolver key -> what picking one card does, worded for the entry a client offers on that card.
CHOICE_PICKS: dict[str, str] = {}


ASSIGNMENT_SEPARATOR = "@"


def assignment_token(card_id: str, battlefield: int) -> str:
    """The candidate string pairing the Personality ``card_id`` with the battlefield at index
    ``battlefield``: how :class:`~.AssignUnits` names one place a unit could go."""
    return f"{card_id}{ASSIGNMENT_SEPARATOR}{battlefield}"


def assignment(token: str) -> tuple[str, int]:
    """The Personality and battlefield index :func:`~.assignment_token` encoded.

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

    A candidate pairs a unit with a battlefield rather than naming either alone, because assigning
    is a choice of *where* and one Personality may go to any battlefield the attack made. Read a
    choice through :func:`~.assignment` rather than splitting the string. The whole seat answers at
    once: the CR has each seat assign simultaneously, so this is one request per seat rather than
    one per unit.

    Assigning nothing is a well-formed answer, since the CR lets a seat keep some or all of its
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
class ChooseInterruptEffect(ChooseOption):
    """Which of the action's effects the Interrupt just taken answers, asked only when the
    forecast holds more than one it could. The candidates are the effects as the seat reads
    them. Answered through its own handler rather than a resolver; ``resolver`` names nothing.
    Backing out unwinds the Interrupt action, which has moved nothing yet."""

    @property
    def cancellable(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class ChooseInterruptTarget(DecisionRequest):
    """The seat must choose the target of the Interrupt it has just taken, for a card that reads
    "Interrupt: Target your X". The candidates are the cards the Interrupt may target, all in
    play, so a client renders them as board selections. Backing out unwinds the Interrupt action,
    which has moved nothing yet.

    Attributes
    ----------
    card_id : str
        The card whose Interrupt is being taken.
    card_name : str
        Its title, for the prompt.
    effect : str
        The action's effect the Interrupt answers, as its description reads, to find it again in
        the forecast once the target is chosen.
    interrupt_key : str, optional
        The key of the Interrupt taken, for one a keyword confers. Default None, the one the card
        prints.
    """

    card_id: str
    card_name: str
    effect: str
    interrupt_key: str | None = None

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return f"Choose a target for {self.card_name}"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)

    @property
    def cancellable(self) -> bool:
        return True


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


# What a seat answers :class:`~.FocusOrStrike` with: the top of its own Fate deck, taken unseen, or
# the strike that ends the focusing. A card in hand is named by :func:`~.focus_token` instead.
DECK_TOP = "deck:top"
STRIKE = "strike"
HAND_SOURCE = "hand:"


def focus_token(card_id: str) -> str:
    """The candidate string naming the hand card ``card_id`` as something to focus: how
    :class:`~.FocusOrStrike` offers one, told apart from ``deck:top`` and ``strike`` by its prefix
    rather than by elimination."""
    return f"{HAND_SOURCE}{card_id}"


def focus_source(token: str) -> str:
    """The hand card :func:`~.focus_token` encoded. Raise ``ValueError`` for any other token."""
    if not token.startswith(HAND_SOURCE) or token == HAND_SOURCE:
        raise ValueError(f"not a hand focus token: {token!r}")
    return token[len(HAND_SOURCE) :]


@dataclass(frozen=True, slots=True)
class FocusOrStrike(DecisionRequest):
    """The seat whose option it is must focus one card or strike (CR, Duel).

    The candidates are source tokens rather than card ids, because focusing off the top of the deck
    names no card the seat may see: :func:`~.focus_token` for each card in hand, ``deck:top``, and
    ``strike``. Read a choice by comparing it against those rather than by splitting the string.

    A seat with nothing left to focus is never asked, so a request that exists always offers a real
    choice. Striking is not a decline: it is the answer that ends the focusing, so it sits among the
    candidates rather than on a decline button.
    """

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Focus a card or strike"

    @property
    def confirm_label(self) -> str:
        return "Focus"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseFocusEffect(DecisionRequest):
    """The active player must name the next revealed Focus Effect to resolve (CR, Duel).

    The candidates are the focused cards still carrying an unresolved Focus Effect, so a client
    offers them where they lie in the focusing areas. The seat picks one at a time and is asked again
    until none are left, which is the CR's "in an order chosen by the active player".

    There is no answer that declines. A Focus Effect resolves whether its controller wants it to, and
    a card whose own text makes it optional asks that question itself once it is resolving. The seat
    is asked only while two or more are left, since one has no order to choose.
    """

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose the next Focus Effect to resolve"

    @property
    def confirm_label(self) -> str:
        return "Resolve"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class ChooseNextTrigger(DecisionRequest):
    """The active player must name the triggered ability that resolves next, when one occurrence
    has triggered several: "If more than one of these things conflict, the active player decides
    the order in which they happen" (CR, Timing Conflicts).

    The candidates are keys for the triggered abilities still to resolve, whoever controls them,
    the event's card's for a rulebook effect: the card's id, with ``#n`` appended where it has more
    than one. A card in a hand is never among them, since naming it would show what its owner
    holds. The seat is asked once for each, the last included. An ability its text makes optional
    asks that question of its own controller once it resolves (CR, Choices), and nothing backs
    out, since what triggered them has already happened.

    Attributes
    ----------
    cards : tuple of str
        The card each candidate fires on, in candidate order.
    labels : tuple of str
        Each candidate's name, its printed trait where it can be read, in candidate order.

    Raises
    ------
    ValueError
        If ``cards`` or ``labels`` does not name one entry per candidate.
    """

    cards: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not len(self.cards) == len(self.labels) == len(self.candidates):
            raise ValueError("a trigger window names a card and a label for each candidate")

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        return "Choose the next triggered ability to resolve"

    def accepts(self, response: DecisionResponse) -> bool:
        return _chooses_exactly_one(self, response)


@dataclass(frozen=True, slots=True)
class Confirm(DecisionRequest):
    """The seat must answer a yes/no question naming what it is being asked to do.

    Answering yes returns the candidates. Answering no returns none. A client renders this as a
    yes/no question rather than a board selection.

    Attributes
    ----------
    question : str
        The question as the seat reads it, naming the cards it concerns.
    resolver : str
        The registered choice resolver that turns the answer into effects.
    source_id : str, optional
        A card id handed to the resolver as its context, as for :class:`~.ChooseCards`. Default
        None.
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
    """The seat must choose between ``minimum`` and ``maximum`` of the candidate cards, a
    variable-count target, as when a triggered effect targets "zero to two" cards. The chosen ids
    feed the named resolver, whose effects apply once the choice is made. The candidates are the
    cards the effect may legally target, all in play, so a client renders them as board selections.

    Attributes
    ----------
    minimum : int
        The fewest cards the seat may choose, zero when the effect is optional.
    maximum : int
        The most cards the seat may choose.
    resolver : str
        The registered choice resolver that turns the chosen ids into effects.
    source_id : str, optional
        A card id handed to the resolver as its context. Which card that is belongs to the resolver,
        often the one whose trigger raised the choice, sometimes the card being acted on. None
        when the rulebook raises the choice and there is no card to name. Default None.
    resolver_context : tuple of str, optional
        What an earlier step of the same choice settled, handed to the resolver alongside the chosen
        ids. A resolver is otherwise given only what was picked and one source card. Default empty.
    declinable : bool, optional
        Whether choosing nothing is an answer as well as a count within the bounds, as "may target
        and move home exactly two units" reads. Default False.
    options : tuple of str, optional
        Named answers offered beside the cards, for a text whose alternative is not on the board:
        Tamori Tsushima creates a Yojimbo instead of putting a Ring into play. One of them is a
        whole answer, so a request carrying them takes one card at a time. Default none.
    """

    minimum: int
    maximum: int
    resolver: str
    source_id: str | None = None
    resolver_context: tuple[str, ...] = ()
    declinable: bool = False
    options: tuple[str, ...] = ()

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        registered = CHOICE_PROMPTS.get(self.resolver)
        asked = self._asked() if registered is None else registered
        note = self.limit_note(partial)
        return f"{asked} ({note})" if note else asked

    def _asked(self) -> str:
        cards = "card" if self.maximum == 1 else "cards"
        if self.minimum == 0:
            return f"Choose up to {self.maximum} {cards}"
        if self.minimum == self.maximum:
            return f"Choose {self.minimum} {cards}"
        return f"Choose {self.minimum} to {self.maximum} {cards}"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        if not chosen and self.declinable:
            return True
        if len(chosen) == 1 and chosen[0] in self.options:
            return True
        distinct = set(chosen)
        return (
            len(distinct) == len(chosen)
            and self.minimum <= len(chosen) <= self.maximum
            and distinct <= set(self.candidates)
            and all(limit.satisfied(chosen) for limit in self.limits)
        )

    @property
    def pick_label(self) -> str:
        """What picking one card does, as a client words the entry it offers on the card."""
        return CHOICE_PICKS.get(self.resolver, "Choose")

    @property
    def names_one_answer(self) -> bool:
        """Whether the seat answers by naming one thing, a card or one of ``options``. Such a
        question has nothing to confirm, so a client offers each card's own entry on the card and
        each option on a button, rather than putting the board into selection mode."""
        return bool(self.options)

    @property
    def cancellable(self) -> bool:
        """Backing out unwinds the whole action that raised it, cost included."""
        return True


@dataclass(frozen=True, slots=True)
class ArrangeCards(DecisionRequest):
    """The seat must put every candidate in an order, as when a card says "put the rest back in any
    order" or "put them on the bottom of your deck in any order".

    The answer names every candidate exactly once, in the order the seat placed them: the first
    named is placed first and each later one goes outside it, so for a top placement the last named
    ends on top and for a bottom placement the last named ends on the bottom. A client that has the
    seat click cards one at a time onto the deck sends them in click order.

    Attributes
    ----------
    resolver : str
        The registered choice resolver that turns the order into effects.
    source_id : str or None
        A card id handed to the resolver as its context, or None.
    to_bottom : bool
        Whether the cards are going to the bottom of the deck rather than the top. It decides the
        wording and which order :attr:`unchanged` is.
    """

    resolver: str
    source_id: str | None
    to_bottom: bool

    def prompt(self, partial: DecisionResponse = DecisionResponse()) -> str:
        registered = CHOICE_PROMPTS.get(self.resolver)
        if registered is not None:
            return registered
        end = "on the bottom of your deck" if self.to_bottom else "back on your deck"
        return f"Put them {end} in any order"

    def accepts(self, response: DecisionResponse) -> bool:
        chosen = response.choices
        return len(chosen) == len(self.candidates) and set(chosen) == set(self.candidates)

    @property
    def pick_label(self) -> str:
        """What placing one card does, as a client words the entry it offers on the card."""
        return "Put on the bottom of your deck" if self.to_bottom else "Put on top of your deck"

    @property
    def unchanged(self) -> tuple[str, ...]:
        """The answer that leaves the cards in the order they were looked at, top first: the
        candidates reversed for a top placement, since the last placed ends on top, and in order for
        a bottom one. A client offers it as "Keep Order"."""
        return self.keeping_order(())

    def keeping_order(self, placed: tuple[str, ...]) -> tuple[str, ...]:
        """The answer that places ``placed`` as the seat already has and the rest in the order they
        were looked at, so "Keep Order" applies to whatever is still in the window."""
        rest = tuple(card_id for card_id in self.candidates if card_id not in placed)
        return (*placed, *(rest if self.to_bottom else reversed(rest)))


@dataclass(frozen=True, slots=True)
class ChooseDistribution(DecisionRequest):
    """The seat must divide ``count`` identical creations among one or more of the candidates, as
    when a card creates several Followers and its controller chooses how to attach them.

    The answer names a candidate once per creation it takes, so an id appearing twice takes two
    and one left out takes none.

    Attributes
    ----------
    count : int
        How many creations there are to divide. All of them are placed, and the seat chooses where
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
