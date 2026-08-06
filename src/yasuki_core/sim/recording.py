from dataclasses import dataclass, field

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.log import Act, Cancel, GameLog
from yasuki_core.engine.rules.state import GameState
from yasuki_core.sim.metrics import Metric


@dataclass(frozen=True, slots=True)
class Sample:
    """One seat's completed turn: metrics read at either end of it, and actions counted across it."""

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
        The turns recorded so far, in order. A turn appears once its end has been observed, so
        every row carries every name — a run that raises part-way through a turn drops it rather
        than reporting one with its end-of-turn columns missing.

    All three sources land in one sample per turn, so a name used in two of them would collide.
    """

    metrics: dict[str, Metric]
    end_of_turn: dict[str, Metric] = field(default_factory=dict)
    actions: dict[str, type[Action]] = field(default_factory=dict)
    log: GameLog | None = None
    samples: list[Sample] = field(default_factory=list)
    _open: Sample | None = field(default=None, init=False)
    _log_offset: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.actions and self.log is None:
            raise ValueError("counting actions needs the log they are recorded on")

    def turn_began(self, game: GameState) -> None:
        seat = game.active
        values = {name: metric(game, seat) for name, metric in self.metrics.items()}
        values.update(dict.fromkeys(self.actions, 0))
        self._open = Sample(turn=game.turn, seat=seat, values=values)
        if self.log is not None:
            self._log_offset = len(self.log.entries)

    def turn_ended(self, game: GameState, seat: PlayerId) -> None:
        open_turn = self._open
        if open_turn is None:
            raise RuntimeError(f"{seat.name}'s turn ended, but no turn had begun")
        if open_turn.seat is not seat:
            raise RuntimeError(
                f"{seat.name}'s turn ended, but the open turn is {open_turn.seat.name}'s"
            )
        open_turn.values.update(
            {name: metric(game, seat) for name, metric in self.end_of_turn.items()}
        )
        for name in self._acted(seat):
            open_turn.values[name] += 1
        self.samples.append(open_turn)
        self._open = None

    def _acted(self, seat: PlayerId) -> list[str]:
        """The counted name of each action ``seat`` took this turn, in order.

        A cancelled action is dropped rather than counted: cancelling backs out the action that
        raised the pending decision, so it never happened. An undone action needs no such handling —
        undo pops it off the tape.
        """
        if not self.actions or self.log is None:
            return []
        taken: list[str] = []
        last_counted: str | None = None
        for entry in self.log.entries[self._log_offset :]:
            if isinstance(entry, Act) and entry.seat is seat:
                last_counted = next(
                    (name for name, kind in self.actions.items() if isinstance(entry.action, kind)),
                    None,
                )
                if last_counted is not None:
                    taken.append(last_counted)
            elif isinstance(entry, Cancel) and entry.seat is seat and last_counted is not None:
                taken.pop()
                last_counted = None
        return taken

    def series(self, seat: PlayerId, name: str) -> list[tuple[int, int]]:
        """``(turn, value)`` for one seat and one metric, in turn order."""
        return [(s.turn, s.values[name]) for s in self.samples if s.seat is seat]
