from enum import Enum


class Segment(Enum):
    """The Attack Phase's segments, in the order the CR walks them. A battle fought inside the Fight
    Segment has segments of its own — see :class:`~.BattleSegment`."""

    DECLARATION = "declaration"
    MANEUVERS = "maneuvers"
    FIGHT = "fight"


class BattleSegment(Enum):
    """One battle's segments, in the order the CR's Battle Sequence walks them. Nested inside the
    Attack Phase's :class:`Segment.FIGHT`, which is where battles are fought.

    Only the first two are Action Rounds — the CR's own list of round types names them and stops
    there. The last two are named because the battle passes through them and cards act around them,
    not because a seat is asked anything in either.
    """

    ENGAGE = "engage"
    COMBAT = "combat"
    RESOLUTION = "resolution"
    AFTER_RESOLUTION = "after_resolution"
