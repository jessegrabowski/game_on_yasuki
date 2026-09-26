from dataclasses import dataclass, field
from enum import Enum
from typing import NamedTuple

from yasuki_core.engine.players import PlayerId


class DuelWork:
    """Marker for a work item that is a step of the duel's own procedure.

    A duel that ends before its steps run drops them off the stack, so what is the duel's own has to
    be distinguishable from the work of whatever created it. Carried as a base class rather than
    matched by type, so a step added later cannot be forgotten by the filter.
    """

    __slots__ = ()


class DuelStep(Enum):
    """Which step of the duel procedure is open.

    The CR's own sequence, minus the steps nothing reaches yet: a challenge that may be refused,
    the focusing loop the duelists alternate in, the reveal a strike causes, and the resolution
    that reads the totals. A duel that has ended sits at :attr:`ENDED` whether it resolved or not,
    since a card asking whether the duel is over should not have to know which way it finished.
    """

    CHALLENGE = "challenge"
    FOCUSING = "focusing"
    REVEAL = "reveal"
    RESOLUTION = "resolution"
    ENDED = "ended"


class DuelOutcome(NamedTuple):
    """What resolving a duel did, recorded as it happened.

    Attributes
    ----------
    winner : PlayerId or None
        The seat whose Personality won, or None where nobody won: a tie between two duelists the
        Duelist tiebreak cannot separate, and any duel that ended without resolution.
    losers : tuple of PlayerId
        The seats whose Personalities lost, which is both of them on a tie and neither on a duel
        that ended without resolution. Recorded rather than derived from ``winner``, because an
        effect may alter one Personality's outcome without altering the other's (CR, Duel).
    totals : dict mapping PlayerId to int
        What each seat's Personality totalled: its duel stat plus the Focus Values of its focused
        cards. Empty for a duel that never reached the reveal.
    resolved : bool
        Whether the duel resolved at all. False for a refused challenge and for a duel a duelist
        left play in the middle of, whose Focus Effects do not resolve either.
    """

    winner: PlayerId | None
    losers: tuple[PlayerId, ...]
    totals: dict[PlayerId, int]
    resolved: bool


@dataclass(slots=True)
class DuelRecord:
    """The duel now being fought: who is in it, where the procedure stands, and how it ended.

    The focused cards are not here. Each seat focuses into a zone of its own
    (:attr:`~yasuki_core.engine.table.ZoneRole.FOCUS`), so a focused card is somewhere the table
    already knows about and redaction already hides, rather than an id in this record that every
    query for "where is this card" would have to learn.

    Attributes
    ----------
    challenger : PlayerId
        The seat whose card created the duel.
    challenged : PlayerId
        The seat challenged, which is the seat the focusing loop gives the first option to.
    challenger_duelist : str
        The id of the challenger's Personality in the duel.
    challenged_duelist : str
        The id of the challenged seat's Personality in the duel.
    source : str
        The id of the card that created the duel, so a consequence can name what set it.
    step : DuelStep
        Which step of the procedure is open. Default ``DuelStep.CHALLENGE``.
    option : PlayerId or None
        The seat whose option it is to focus or strike, or None outside the focusing loop.
        Default None.
    focused : dict mapping PlayerId to int
        How many times each seat has focused, which is what a focus limit counts. A seat that has
        not focused is absent, so read it through :meth:`focuses`. Default empty.
    struck : PlayerId or None
        The seat that struck, ending the focusing, or None until one has. Default None.
    outcome : DuelOutcome or None
        What the duel did, or None until it has ended. Default None.
    """

    challenger: PlayerId
    challenged: PlayerId
    challenger_duelist: str
    challenged_duelist: str
    source: str
    step: DuelStep = DuelStep.CHALLENGE
    option: PlayerId | None = None
    focused: dict[PlayerId, int] = field(default_factory=dict)
    struck: PlayerId | None = None
    outcome: DuelOutcome | None = None

    def duelist_of(self, seat: PlayerId) -> str:
        """The id of ``seat``'s Personality in the duel. Raise ``KeyError`` for a seat not in it."""
        if seat is self.challenger:
            return self.challenger_duelist
        if seat is self.challenged:
            return self.challenged_duelist
        raise KeyError(f"{seat} is not in this duel")

    def opponent_of(self, seat: PlayerId) -> PlayerId:
        """The other seat in the duel. Raise ``KeyError`` for a seat not in it."""
        if seat is self.challenger:
            return self.challenged
        if seat is self.challenged:
            return self.challenger
        raise KeyError(f"{seat} is not in this duel")

    def focuses(self, seat: PlayerId) -> int:
        """How many times ``seat`` has focused in this duel."""
        return self.focused.get(seat, 0)
