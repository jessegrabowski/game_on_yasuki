from dataclasses import dataclass, field

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.sim.metrics import Metric


@dataclass(frozen=True, slots=True)
class Sample:
    """One seat's metrics over one of its turns, read at either end of it."""

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
    samples : list of Sample
        What has been recorded so far, in turn order.

    Both land in one sample per turn, so a name used in each would collide.
    """

    metrics: dict[str, Metric]
    end_of_turn: dict[str, Metric] = field(default_factory=dict)
    samples: list[Sample] = field(default_factory=list)

    def turn_began(self, game: GameState) -> None:
        seat = game.active
        values = {name: metric(game, seat) for name, metric in self.metrics.items()}
        self.samples.append(Sample(turn=game.turn, seat=seat, values=values))

    def turn_ended(self, game: GameState, seat: PlayerId) -> None:
        finished = self.samples[-1]
        if finished.seat is not seat:
            raise RuntimeError(
                f"{seat.name}'s turn ended, but the open sample is {finished.seat}'s"
            )
        finished.values.update(
            {name: metric(game, seat) for name, metric in self.end_of_turn.items()}
        )

    def series(self, seat: PlayerId, name: str) -> list[tuple[int, int]]:
        """``(turn, value)`` for one seat and one metric, in turn order."""
        return [(s.turn, s.values[name]) for s in self.samples if s.seat is seat]
