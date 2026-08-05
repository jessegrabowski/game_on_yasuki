from dataclasses import dataclass, field

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.state import GameState
from yasuki_core.sim.metrics import Metric


@dataclass(frozen=True, slots=True)
class Sample:
    """One seat's metrics at the start of one of its turns."""

    turn: int
    seat: PlayerId
    values: dict[str, int]


@dataclass(slots=True)
class TurnRecorder:
    """
    Samples ``metrics`` for the active seat as each turn begins.

    Only the active seat, because only it has just straightened: a producer another seat bowed to
    pay stays bowed through this turn, so its numbers would read low every other turn. Over a game
    each seat is sampled on its own turns, which is the series a per-turn question wants.

    Attributes
    ----------
    metrics : dict mapping str to callable
        The metrics to sample, by the name they are reported under.
    samples : list of Sample
        What has been recorded so far, in turn order.
    """

    metrics: dict[str, Metric]
    samples: list[Sample] = field(default_factory=list)

    def turn_began(self, game: GameState) -> None:
        seat = game.active
        self.samples.append(
            Sample(
                turn=game.turn,
                seat=seat,
                values={name: metric(game, seat) for name, metric in self.metrics.items()},
            )
        )

    def series(self, seat: PlayerId, name: str) -> list[tuple[int, int]]:
        """``(turn, value)`` for one seat and one metric, in turn order."""
        return [(s.turn, s.values[name]) for s in self.samples if s.seat is seat]
