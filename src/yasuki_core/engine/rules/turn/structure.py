from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import ActionTiming
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment, Segment


class Phase(Enum):
    ACTION = "action"
    BATTLE = "battle"
    DYNASTY = "dynasty"


# The phases of a turn in the order the active player works through them. After DYNASTY the turn
# ends with the fate draw and play passes to the next seat (handled by the flow layer).
TURN_PHASES: tuple[Phase, ...] = (Phase.ACTION, Phase.BATTLE, Phase.DYNASTY)


@dataclass(frozen=True, slots=True)
class RoundTimings:
    """What an Action Round permits, split the way the CR splits it — the active player and everyone
    else are allowed different designators in the same round.

    Attributes
    ----------
    active : frozenset of ActionTiming
        What the active player may take.
    others : frozenset of ActionTiming
        What every other player may take. Empty means they hold no opportunity in this round at all.
    """

    active: frozenset[ActionTiming]
    others: frozenset[ActionTiming]


# What each phase's Action Round permits. The Battle phase permits only the declaration: a battle's
# own Engage and Combat Segments will open rounds of their own.
PHASE_TIMINGS: dict[Phase, RoundTimings] = {
    Phase.ACTION: RoundTimings(
        active=frozenset({ActionTiming.OPEN, ActionTiming.LIMITED}),
        others=frozenset({ActionTiming.OPEN}),
    ),
    Phase.BATTLE: RoundTimings(active=frozenset({ActionTiming.ATTACK}), others=frozenset()),
    Phase.DYNASTY: RoundTimings(active=frozenset({ActionTiming.DYNASTY}), others=frozenset()),
}

# The Response Step, which the ShE datasheet inserts after an action finishes resolving and before
# the last step of the Action Sequence. It is a round of its own, open to every seat, and it permits
# nothing but Responses: no one may take an Open action in the middle of someone else's action.
RESPONSE_TIMINGS = RoundTimings(
    active=frozenset({ActionTiming.RESPONSE}),
    others=frozenset({ActionTiming.RESPONSE}),
)


class RoundKind(Enum):
    """What sort of Action Round is open.

    A round is suspended and resumed by kind rather than by how deep the round stack is. Depth only
    answers "is something suspended beneath this", which stops meaning "this is a Response Step" the
    moment anything else pushes — a battle's Engage and Combat Segments among them.
    """

    PHASE = "phase"
    RESPONSE = "response"
    BATTLE_SEGMENT = "battle_segment"


@dataclass(frozen=True, slots=True)
class ActionRound:
    """The Action Round currently open — the CR's unit of "who may act now, and when this ends".

    A round runs until every seat has passed consecutively; taking an action resets that count and
    hands the opportunity on. Every phase opens one, and a battle's Engage and Combat Segments will
    open their own.

    Attributes
    ----------
    timings : RoundTimings
        The designators this round permits, per seat. A pass carries none and is always allowed.
    priority : PlayerId
        The seat holding the opportunity to act.
    passes : int
        How many seats have passed in a row. Default 0.
    kind : RoundKind
        What sort of round this is, which decides how it closes. Default ``RoundKind.PHASE``.
    """

    timings: RoundTimings
    priority: PlayerId
    passes: int = 0
    kind: RoundKind = RoundKind.PHASE


# What each battle segment that is an Action Round permits. Both are open to every seat and permit
# only their own designator, and both start with the Defender (CR, Battle Sequence).
BATTLE_SEGMENT_TIMINGS: dict[BattleSegment, RoundTimings] = {
    BattleSegment.ENGAGE: RoundTimings(
        active=frozenset({ActionTiming.ENGAGE}), others=frozenset({ActionTiming.ENGAGE})
    ),
    BattleSegment.COMBAT: RoundTimings(
        active=frozenset({ActionTiming.BATTLE}), others=frozenset({ActionTiming.BATTLE})
    ),
}


class Turn(Enum):
    """The turn itself as a stage of play, the one enclosing every :class:`Phase`."""

    CURRENT = "turn"


class Boundary(Enum):
    """Which edge of a stage of play a :class:`Moment` names."""

    BEGINNING = "beginning"
    END = "end"


# The stretches of play a Moment can name the edge of: the turn, one of its phases, or one of the
# Attack Phase's segments.
Stage = Turn | Phase | Segment | BattleSegment


@dataclass(frozen=True, slots=True)
class Moment:
    """A boundary of a stage of play, worded the way a card prints one — "at the end of the turn",
    "at the beginning of the Action Phase".

    Attributes
    ----------
    stage : Turn, Phase, Segment or BattleSegment
        The stretch of play whose edge this names.
    boundary : Boundary
        Which edge of that stretch.
    """

    stage: Stage
    boundary: Boundary

    def describe(self) -> str:
        return f"at the {self.boundary.value} of the {self._stage_name()}"

    def _stage_name(self) -> str:
        match self.stage:
            case Turn() as turn:
                return turn.value
            case Phase() as phase:
                return f"{phase.value.title()} Phase"
            case Segment() | BattleSegment() as segment:
                return f"{segment.value.replace('_', ' ').title()} Segment"
            case _:
                raise ValueError(f"no name for the stage {self.stage!r}")


END_OF_TURN = Moment(Turn.CURRENT, Boundary.END)
BEGINNING_OF_COMBAT = Moment(BattleSegment.COMBAT, Boundary.BEGINNING)

# The moments the flow reaches. Any other Moment is constructible and correctly worded, so an effect
# delayed to one would be held for the rest of the game with nothing to resolve it. The battle
# segments' beginnings are taken from the map the flow opens their rounds from, so a segment that
# becomes an Action Round is fired and listed in the one edit.
FIRED_MOMENTS: frozenset[Moment] = frozenset(
    {END_OF_TURN, *(Moment(segment, Boundary.BEGINNING) for segment in BATTLE_SEGMENT_TIMINGS)}
)


def flow_resolves(moment: Moment) -> bool:
    """Whether the flow reaches ``moment``. A Moment names a stage and a boundary and nothing else,
    so it stands for every occurrence of that stage at once."""
    return moment in FIRED_MOMENTS
