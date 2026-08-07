from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median, quantiles

import numpy as np

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action
from yasuki_core.engine.rules.agents import Agent
from yasuki_core.engine.rules.policies import Policy
from yasuki_core.engine.runner import Controls, play_game
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_setup import build_state_from_deck
from yasuki_core.sim.metrics import Metric
from yasuki_core.sim.recording import Sample, TurnRecorder


# One stream per consumer of randomness, spawned in this order. Positions are part of the
# contract: appending a name leaves every existing stream untouched, but reordering or inserting
# one silently changes every run.
STREAMS = ("deal", "engine")


@dataclass(frozen=True, slots=True)
class Game:
    """One played game: its position in the run, and what was recorded over its turns.

    The run's seed and this index together reproduce the game, since every stream it used was
    spawned from that seed at that position.
    """

    index: int
    samples: list[Sample]


def run_games(
    deck_path: Path | str,
    policy: Policy,
    agent: Agent,
    *,
    games: int,
    turn_limit: int,
    seed: int = 0,
    metrics: dict[str, Metric] | None = None,
    end_of_turn: dict[str, Metric] | None = None,
    actions: dict[str, type[Action]] | None = None,
) -> list[Game]:
    """
    Play ``deck_path`` against itself ``games`` times, varying only the shuffle.

    Every stream is spawned from ``seed`` through :class:`numpy.random.SeedSequence`, one child per
    game and one grandchild per entry in :data:`STREAMS`. Children are fixed by position, so a run
    reproduces from its seed and game count, and lengthening a run leaves the games it already had
    identical. Everything else is held constant on purpose: a run that varied the deck or the
    policy alongside the seed would report a spread that answers nothing.

    Reproducibility relies on ``policy`` and ``agent`` being deterministic, which the shipped ones
    are. A stochastic policy holds its own stream and is not reseeded per game, so repeating a run
    would not repeat it; giving it a spawned stream means adding a name to :data:`STREAMS`.

    Parameters
    ----------
    deck_path : path or str
        The decklist both seats play — a mirror match.
    policy : Policy
        Drives every seat.
    agent : Agent
        Answers the decisions those choices raise, for every seat.
    games : int
        How many games to play.
    turn_limit : int
        The last turn of each game.
    seed : int, optional
        The run's root seed, from which every stream is spawned. Default 0.
    metrics : dict mapping str to callable, optional
        Sampled as each turn begins. Default none.
    end_of_turn : dict mapping str to callable, optional
        Sampled as each turn ends. Default none.
    actions : dict mapping str to Action subclass, optional
        Counted over each turn. Default none.

    Returns
    -------
    list of Game
        One entry per game, in seed order.
    """
    played: list[Game] = []
    for index, game_streams in enumerate(np.random.SeedSequence(seed).spawn(games)):
        streams = dict(zip(STREAMS, game_streams.spawn(len(STREAMS)), strict=True))
        table, first_player = build_state_from_deck(
            deck_path, rng=np.random.default_rng(streams["deal"])
        )
        session = EngineSession.start(table, first_player, seed=_engine_seed(streams["engine"]))
        recorder = TurnRecorder(
            metrics or {},
            end_of_turn=end_of_turn or {},
            actions=actions or {},
            log=session.log if actions else None,
        )
        controls = {seat: Controls(policy, agent) for seat in PlayerId}
        play_game(session, controls, turn_limit=turn_limit, observer=recorder)
        played.append(Game(index=index, samples=recorder.samples))
    return played


@dataclass(frozen=True, slots=True)
class Summary:
    """What a set of games said about one metric on one turn.

    Attributes
    ----------
    games : int
        How many games contributed a value.
    mean : float
        The average.
    median : float
        The middle value.
    low : float
        The 10th percentile.
    high : float
        The 90th percentile.
    """

    games: int
    mean: float
    median: float
    low: float
    high: float


def summarize(values: Sequence[float]) -> Summary:
    """
    Describe ``values`` as a distribution.

    A single value reports itself as every percentile, which is what one game should say.

    Raise ValueError if ``values`` is empty.
    """
    if not values:
        raise ValueError("cannot summarize an empty set of games")
    deciles = quantiles(values, n=10)
    return Summary(
        games=len(values),
        mean=fmean(values),
        median=median(values),
        low=deciles[0],
        high=deciles[-1],
    )


def per_turn(played: Sequence[Game], seat: PlayerId, name: str) -> dict[int, list[float]]:
    """Every game's value for ``name`` on each of ``seat``'s turns, keyed by turn.

    A turn some games never reached is reported from the games that did, so a late turn thins out
    rather than disappearing — which is why :class:`Summary` carries its own game count.
    """
    columns: dict[int, list[float]] = {}
    for game in played:
        for sample in game.samples:
            if sample.seat is seat:
                columns.setdefault(sample.turn, []).append(sample.values[name])
    return columns


def summarize_per_turn(played: Sequence[Game], seat: PlayerId, name: str) -> dict[int, Summary]:
    """``Summary`` of ``name`` for each of ``seat``'s turns, in turn order."""
    columns = per_turn(played, seat, name)
    return {turn: summarize(columns[turn]) for turn in sorted(columns)}


def share_reaching(
    played: Sequence[Game], seat: PlayerId, name: str, *, at_least: float, by_turn: int
) -> float:
    """
    The fraction of games where ``seat``'s ``name`` reached ``at_least`` on or before ``by_turn``.

    This is the shape of "probability of X by turn N". A game that ended before ``by_turn`` counts
    against the fraction unless it had already reached the threshold, since not getting there is
    the outcome being measured.

    Raise ValueError if ``played`` is empty.
    """
    if not played:
        raise ValueError("cannot take a share of no games")
    reached = sum(
        any(
            sample.seat is seat and sample.turn <= by_turn and sample.values[name] >= at_least
            for sample in game.samples
        )
        for game in played
    )
    return reached / len(played)


def _engine_seed(stream: np.random.SeedSequence) -> int:
    """An integer seed for the rules engine, which records one in its log.

    The deal takes a generator directly, but a game log carries ``seed: int`` and replay rebuilds
    the game's generator from it — so the engine's stream has to survive as a number.
    """
    return int(stream.generate_state(1, dtype=np.uint32)[0])
