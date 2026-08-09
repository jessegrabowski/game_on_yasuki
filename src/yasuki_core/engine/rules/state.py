from dataclasses import dataclass, field
from enum import Enum

from numpy.random import Generator, default_rng

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.actions import ActionTiming
from yasuki_core.engine.rules.decisions import DecisionRequest
from yasuki_core.engine.rules.modifiers import Modifier
from yasuki_core.engine.rules.work import WorkItem


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


# What each phase's Action Round permits. The Battle phase permits nothing of its own: battles are
# declared there and their Engage and Combat Segments are Action Rounds in their own right.
PHASE_TIMINGS: dict[Phase, RoundTimings] = {
    Phase.ACTION: RoundTimings(
        active=frozenset({ActionTiming.OPEN, ActionTiming.LIMITED}),
        others=frozenset({ActionTiming.OPEN}),
    ),
    Phase.BATTLE: RoundTimings(active=frozenset(), others=frozenset()),
    Phase.DYNASTY: RoundTimings(active=frozenset({ActionTiming.DYNASTY}), others=frozenset()),
}


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
    """

    timings: RoundTimings
    priority: PlayerId
    passes: int = 0


@dataclass(slots=True)
class GameState:
    """The mutable state of one rules-driven game.

    Composes the shared :class:`TableState` (zones, decks, cards, positions) with the turn-level
    bookkeeping the rules engine owns: whose turn it is, the current phase, the per-seat gold pool,
    and once-per usage flags. The table stays a pure substrate so the manual sandbox keeps using it
    unchanged; the rules engine layers its own state on top.

    Attributes
    ----------
    table : TableState
        The shared board substrate the game plays on.
    first_player : PlayerId
        The seat that took the first turn, fixed at game start.
    active : PlayerId
        The seat whose turn it currently is.
    turn : int
        The turn counter, starting at 1 and incremented on each new player-turn.
    phase : Phase
        The current phase of the active player's turn.
    round : ActionRound
        The Action Round open in that phase: who holds the opportunity to act, and how close the
        round is to closing.
    gold : dict mapping PlayerId to int
        Each seat's transient gold pool. Gold produced during a cost payment pools here for further
        costs in the same phase and is cleared at the end of every phase.
    favor_holder : PlayerId or None
        The seat holding the Imperial Favor, or None if no one holds it. Default None.
    loser : PlayerId or None
        The seat that has lost the game, or None while the game is ongoing. Set when a loss
        condition fires (currently a failed Legacy search). Default None.
    once_per : set of str
        Usage flags for once-per-turn and once-per-game abilities (the Inheritance Rule, Proclaim,
        ...), keyed by a caller-chosen string. Default empty.
    seed : int
        The seed recorded for deterministic replay, from which ``rng`` is rebuilt. Default 0.
    rng : numpy.random.Generator
        Every draw the rules engine makes. Replay reconstructs it from ``seed``, so re-running the
        same actions repeats the same draws.
    pending : DecisionRequest or None
        The decision the engine is paused on, awaiting an answer from one seat, or None when the
        engine is free to advance. Default None.
    stack : list of WorkItem
        Deferred engine work — the later steps of an action sequence, run once the current decision
        clears. Ephemeral: replay rebuilds it by re-running the engine, so it is never serialized.
        Default empty.
    modifiers : list of Modifier
        The active recorded stat modifiers — created continuous effects (an ability's grant), kept in
        creation order. Ephemeral: rebuilt by replay and never serialized, like ``stack``, but unlike
        it may be non-empty at rest within a turn, so its order is load-bearing. Default empty.
    """

    table: TableState
    first_player: PlayerId
    active: PlayerId
    turn: int
    phase: Phase
    round: ActionRound
    gold: dict[PlayerId, int]
    favor_holder: PlayerId | None = None
    loser: PlayerId | None = None
    once_per: set[str] = field(default_factory=set)
    seed: int = 0
    # Excluded from equality: two Generator objects compare by identity, so a replayed game would
    # never equal the one it replayed even with an identically seeded stream.
    rng: Generator = field(default_factory=lambda: default_rng(0), compare=False, repr=False)
    pending: DecisionRequest | None = None
    stack: list[WorkItem] = field(default_factory=list)
    modifiers: list[Modifier] = field(default_factory=list)

    @property
    def awaiting_decision(self) -> bool:
        """Whether the engine is paused on a pending decision."""
        return self.pending is not None

    @property
    def game_over(self) -> bool:
        """Whether the game has ended — a seat has lost."""
        return self.loser is not None

    @classmethod
    def start(cls, table: TableState, first_player: PlayerId, *, seed: int = 0) -> "GameState":
        """Begin a game on ``table``: turn 1, ``first_player`` active, the Action phase, and an
        empty gold pool for every seat.

        Parameters
        ----------
        table : TableState
            The dealt board to play on.
        first_player : PlayerId
            The seat taking the first turn.
        seed : int, optional
            Seeds the game's generator and is recorded in its log, which is what lets replay
            rebuild an identical one. Default 0.
        """
        return cls(
            table=table,
            first_player=first_player,
            active=first_player,
            turn=1,
            phase=Phase.ACTION,
            round=ActionRound(PHASE_TIMINGS[Phase.ACTION], priority=first_player),
            gold={seat: 0 for seat in table.seats},
            seed=seed,
            rng=default_rng(seed),
        )

    def add_gold(self, seat: PlayerId, amount: int) -> None:
        """Add ``amount`` produced gold to ``seat``'s pool."""
        self.gold[seat] += amount

    def spend_gold(self, seat: PlayerId, amount: int) -> bool:
        """Spend ``amount`` from ``seat``'s pool. Return whether the pool covered it; on an
        insufficient pool, leave it untouched and return False."""
        if self.gold[seat] < amount:
            return False
        self.gold[seat] -= amount
        return True

    def clear_gold(self) -> None:
        """Empty every seat's gold pool, as happens at the end of each phase."""
        for seat in self.gold:
            self.gold[seat] = 0

    def use_once(self, key: str) -> bool:
        """Claim the one-time use named ``key``. Return True the first time and record it; return
        False if it was already used."""
        if key in self.once_per:
            return False
        self.once_per.add(key)
        return True

    def has_used(self, key: str) -> bool:
        """Return whether the one-time use named ``key`` has already been claimed."""
        return key in self.once_per
