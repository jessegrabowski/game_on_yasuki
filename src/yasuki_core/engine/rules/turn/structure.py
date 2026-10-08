from dataclasses import dataclass
from enum import Enum

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import Action, ActionTiming
from yasuki_core.engine.rules.vocabulary.segments import (
    BattleSegment,
    Boundary,
    DuelStep,
    Segment,
)


class Phase(Enum):
    ACTION = "action"
    BATTLE = "battle"
    DYNASTY = "dynasty"


# The phases of a turn in the order the active player works through them. After DYNASTY the turn
# ends with the fate draw and play passes to the next seat (handled by the flow layer).
TURN_PHASES: tuple[Phase, ...] = (Phase.ACTION, Phase.BATTLE, Phase.DYNASTY)


@dataclass(frozen=True, slots=True)
class RoundTimings:
    """What an Action Round permits, split the way the CR splits it. The active player and everyone
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


# The Interrupt step, D of the Action Sequence: a round of its own over the effects an action is
# about to resolve, open to every seat and permitting nothing but Interrupts (CR, Interrupt
# Actions: "following an action round which begins with the active player").
INTERRUPT_TIMINGS = RoundTimings(
    active=frozenset({ActionTiming.INTERRUPT}),
    others=frozenset({ActionTiming.INTERRUPT}),
)


class RoundKind(Enum):
    """What sort of Action Round is open.

    A round is suspended and resumed by kind rather than by how deep the round stack is. Depth only
    answers "is something suspended beneath this", which stops meaning "this is a Response Step" the
    moment anything else pushes. A battle's Engage and Combat Segments are among them.
    """

    PHASE = "phase"
    INTERRUPT = "interrupt"
    RESPONSE = "response"
    BATTLE_SEGMENT = "battle_segment"
    DUEL_WINDOW = "duel_window"


# The rounds that are a step inside an action that is still resolving, rather than a round of play in
# their own right. An action taken in one of these answers the action the step was opened over and
# does not become the action the table is resolving, and none of them opens a step of its own.
STEP_ROUNDS = frozenset({RoundKind.INTERRUPT, RoundKind.RESPONSE, RoundKind.DUEL_WINDOW})

# The rounds whose closing resumes work held beneath them: the action an Interrupt step suspended,
# and the remaining steps of a duel. The action they belong to has not finished resolving, so each
# hands the opportunity on from the round it suspended rather than yielding priority in it.
ROUNDS_OVER_HELD_WORK = frozenset({RoundKind.INTERRUPT, RoundKind.DUEL_WINDOW})


@dataclass(frozen=True, slots=True)
class ActionRound:
    """The Action Round currently open: the CR's unit of "who may act now, and when this ends".

    A round runs until every seat has passed consecutively. Taking an action resets that count and
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
    follow_ups : frozenset of Action or None
        The actions the seat holding priority may spend an additional action on, as "take an
        additional Battle from your target Ring" limits it, or None when the opportunity is not
        limited. Dropped as the opportunity passes on. Default None.
    granted_by : str or None
        The card whose additional action the seat holding priority is taking, or None when it
        holds an ordinary opportunity. Dropped as the opportunity passes on. Default None.
    """

    timings: RoundTimings
    priority: PlayerId
    passes: int = 0
    kind: RoundKind = RoundKind.PHASE
    follow_ups: frozenset[Action] | None = None
    granted_by: str | None = None


@dataclass(frozen=True, slots=True)
class AdditionalGrant:
    """An additional action granted by the action now resolving and not yet opened (CR, Additional
    Action).

    Attributes
    ----------
    seat : PlayerId
        The seat granted it.
    source_id : str
        The card whose text grants it.
    follow_ups : frozenset of Action or None
        The actions it is limited to, or None for any the round permits.
    kind : RoundKind
        The kind of round it was granted in, which is the round it opens in: a Response Step taken
        over the action passes it by, and it opens once the round beneath resumes.
    """

    seat: PlayerId
    source_id: str
    follow_ups: frozenset[Action] | None
    kind: RoundKind


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
    """The turn itself as a stage of play, the one enclosing every :class:`~.Phase`."""

    CURRENT = "turn"


class Opportunity(Enum):
    """An additional action limited to some follow-ups, as a stage of play: it opens as the action
    granting it resolves and closes once the seat has taken or passed it (CR, Additional Action)."""

    ADDITIONAL = "additional action"


# The stretches of play a Moment can name the edge of: the turn, one of its phases, one of the
# Attack Phase's segments, a duel's steps, or an additional action.
Stage = Turn | Phase | Segment | BattleSegment | DuelStep | Opportunity


@dataclass(frozen=True, slots=True)
class Moment:
    """A boundary of a stage of play, worded the way a card prints one, such as "at the end of the
    turn" or "at the beginning of the Action Phase".

    Attributes
    ----------
    stage : Turn, Phase, Segment, BattleSegment or DuelStep
        The stretch of play whose edge this names.
    boundary : Boundary
        Which edge of that stretch.
    """

    stage: Stage
    boundary: Boundary

    def describe(self) -> str:
        if self.stage is DuelStep.ENDED and self.boundary is Boundary.BEGINNING:
            # The CR's own wording for a duel's consequences, which is the one edge of a duel's
            # steps a card delays an effect to.
            return "as the duel ends"
        if self.stage is Opportunity.ADDITIONAL:
            return "once the additional action is spent"
        return f"at the {self.boundary.value} of the {self._stage_name()}"

    def _stage_name(self) -> str:
        match self.stage:
            case Turn() as turn:
                return turn.value
            case Phase() as phase:
                return f"{phase.value.title()} Phase"
            case Segment() | BattleSegment() as segment:
                return f"{segment.value.replace('_', ' ').title()} Segment"
            case DuelStep() as step:
                return f"{step.value.title()} Step"
            case _:
                raise ValueError(f"no name for the stage {self.stage!r}")


END_OF_TURN = Moment(Turn.CURRENT, Boundary.END)
# The moments a card can name as the end of a prohibition on straightening: a turn's beginning,
# before its straighten, as in "cannot straighten before your second turn from now begins", and the
# two edges of an Action Phase, as in "until after their controller's next Action Phase begins".
BEGINNING_OF_TURN = Moment(Turn.CURRENT, Boundary.BEGINNING)
BEGINNING_OF_ACTION_PHASE = Moment(Phase.ACTION, Boundary.BEGINNING)
END_OF_ACTION_PHASE = Moment(Phase.ACTION, Boundary.END)
BEGINNING_OF_COMBAT = Moment(BattleSegment.COMBAT, Boundary.BEGINNING)
# "After this battle ends": the battle ends once After Resolution has sent its survivors home
# (CR, After Resolution).
END_OF_BATTLE = Moment(BattleSegment.AFTER_RESOLUTION, Boundary.END)
# "Apply these consequences now": a duel ends when its resolution step closes, and the consequences
# it gave for the winner or the loser resolve as it ends, before its focused cards are discarded
# (CR, Duel).
DUEL_CONSEQUENCES = Moment(DuelStep.ENDED, Boundary.BEGINNING)
# "Take an additional action ... If the Ring was in the discard pile, reshuffle it": what is granted
# for a limited additional action alone, and what waits on it, lasts until the seat has taken or
# passed it.
ADDITIONAL_ACTION_SPENT = Moment(Opportunity.ADDITIONAL, Boundary.END)

# The moments the flow reaches. Any other Moment is constructible and correctly worded, so an effect
# delayed to one would be held for the rest of the game with nothing to resolve it. The battle
# segments' beginnings are taken from the map the flow opens their rounds from, so a segment that
# becomes an Action Round is fired and listed in the one edit.
FIRED_MOMENTS: frozenset[Moment] = frozenset(
    {
        END_OF_TURN,
        END_OF_BATTLE,
        DUEL_CONSEQUENCES,
        ADDITIONAL_ACTION_SPENT,
        *(Moment(segment, Boundary.BEGINNING) for segment in BATTLE_SEGMENT_TIMINGS),
    }
)


def flow_resolves(moment: Moment) -> bool:
    """Whether the flow reaches ``moment``. A Moment names a stage and a boundary and nothing else,
    so it stands for every occurrence of that stage at once."""
    return moment in FIRED_MOMENTS
