from enum import Enum


class Segment(Enum):
    """The Attack Phase's segments, in the order the CR walks them. A battle fought inside the Fight
    Segment has segments of its own, described in :class:`~.BattleSegment`."""

    DECLARATION = "declaration"
    MANEUVERS = "maneuvers"
    FIGHT = "fight"


class BattleSegment(Enum):
    """One battle's segments, in the order the CR's Battle Sequence walks them. Nested inside the
    Attack Phase's :class:`Segment.FIGHT`, which is where battles are fought.

    Only the first two are Action Rounds. The CR's own list of round types names them and stops
    there. The last two are named because the battle passes through them and cards act around them,
    not because a seat is asked anything in either.
    """

    ENGAGE = "engage"
    COMBAT = "combat"
    RESOLUTION = "resolution"
    AFTER_RESOLUTION = "after_resolution"


class DuelStep(Enum):
    """Which step of the duel procedure is open.

    The CR's own sequence: the focusing loop the duelists alternate in, the reveal a strike causes,
    and the resolution that reads the totals. A duel sits at :attr:`ENDED` from the moment its
    resolution step closes, which is when the CR says the duel has ended, and stays there while its
    consequences apply and its focused cards are discarded.
    """

    FOCUSING = "focusing"
    REVEAL = "reveal"
    RESOLUTION = "resolution"
    ENDED = "ended"


class Boundary(Enum):
    """Which edge of a stage of play a moment names."""

    BEGINNING = "beginning"
    END = "end"
