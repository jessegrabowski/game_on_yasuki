from dataclasses import dataclass, field

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.log import Act, Cancel, GameLog
from yasuki_core.engine.rules.state import GameState
from yasuki_core.sim.metrics import Metric


@dataclass(frozen=True, slots=True)
class Sample:
    """One seat's metrics over one of its turns — read at either end, and counted across it."""

    turn: int
    seat: PlayerId
    values: dict[str, int]


@dataclass(slots=True)
class TurnRecorder:
    """
    Samples each seat over its own turns, from whichever end of the turn a metric is canonical at.

    Only the seat whose turn it is, because only it has just straightened: a producer another seat
    bowed to pay stays bowed through this turn, so its numbers would read low every other turn.

    Attributes
    ----------
    metrics : dict mapping str to callable
        Sampled as the turn begins, when the seat has straightened and revealed — what it has to
        spend. Reported under the name each is keyed by.
    end_of_turn : dict mapping str to callable, optional
        Sampled as the turn ends, when the board shows what the seat did with it — bowed producers,
        provinces cleared and refilled face-down. Default empty.
    actions : dict mapping str to Action subclass, optional
        Counted over the turn from the game log: how many actions of that class the seat took. What
        the board cannot say, since a recruited card and a discarded one leave a province looking
        the same. Requires ``log``. Default empty.
    log : GameLog, optional
        The tape of the game being recorded, read between turn boundaries to count ``actions``.
        Default None, which is only valid when nothing is being counted.
    samples : list of Sample
        What has been recorded so far, in turn order.

    All three sources land in one sample per turn, so a name used in two of them would collide.
    """

    metrics: dict[str, Metric]
    end_of_turn: dict[str, Metric] = field(default_factory=dict)
    actions: dict[str, type[Action]] = field(default_factory=dict)
    log: GameLog | None = None
    samples: list[Sample] = field(default_factory=list)
    _turn_start: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.actions and self.log is None:
            raise ValueError("counting actions needs the log they are recorded on")

    def turn_began(self, game: GameState) -> None:
        seat = game.active
        values = {name: metric(game, seat) for name, metric in self.metrics.items()}
        values.update(dict.fromkeys(self.actions, 0))
        self.samples.append(Sample(turn=game.turn, seat=seat, values=values))
        if self.log is not None:
            self._turn_start = len(self.log.entries)

    def turn_ended(self, game: GameState, seat: PlayerId) -> None:
        finished = self.samples[-1]
        if finished.seat is not seat:
            raise RuntimeError(
                f"{seat.name}'s turn ended, but the open sample is {finished.seat}'s"
            )
        finished.values.update(
            {name: metric(game, seat) for name, metric in self.end_of_turn.items()}
        )
        for name in self._acted(seat):
            finished.values[name] += 1

    def _acted(self, seat: PlayerId) -> list[str]:
        """The counted name of each action ``seat`` took this turn, in order.

        A cancelled action is dropped rather than counted: cancelling backs out the action that
        raised the pending decision, so it never happened. An undone action needs no such handling —
        undo pops it off the tape.
        """
        if not self.actions or self.log is None:
            return []
        taken: list[str] = []
        latest: str | None = None
        for entry in self.log.entries[self._turn_start :]:
            if isinstance(entry, Act) and entry.seat is seat:
                latest = next(
                    (name for name, kind in self.actions.items() if isinstance(entry.action, kind)),
                    None,
                )
                if latest is not None:
                    taken.append(latest)
            elif isinstance(entry, Cancel) and entry.seat is seat and latest is not None:
                taken.pop()
                latest = None
        return taken

    def series(self, seat: PlayerId, name: str) -> list[tuple[int, int]]:
        """``(turn, value)`` for one seat and one metric, in turn order."""
        return [(s.turn, s.values[name]) for s in self.samples if s.seat is seat]
