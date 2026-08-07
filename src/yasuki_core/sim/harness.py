import csv
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
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


def write_csv(path: Path | str, played: Sequence[Game], **run: object) -> None:
    """
    Write one row per recorded turn, so a run can be loaded and analysed with real tools.

    Every ``run`` keyword becomes a column repeated on each row — the deck, the policy, the seed,
    whatever identifies the run. That is what lets two runs be concatenated and told apart later,
    and it is why no aggregate is computed here: the numbers worth quoting depend on the question,
    and the question is asked after the run.

    Parameters
    ----------
    path : path or str
        The CSV to write, overwritten if it exists.
    played : sequence of Game
        What :func:`run_games` returned.
    **run
        Provenance columns, written before the per-turn ones.

    Raises
    ------
    ValueError
        If ``played`` holds no samples, since the file would carry a header and nothing else.
    """
    rows = list(sample_rows(played, **run))
    if not rows:
        raise ValueError("no turns were recorded, so there is nothing to write")
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def sample_rows(played: Sequence[Game], **run: object) -> Iterator[dict[str, object]]:
    """One flat row per recorded turn: the run's provenance, then the game, turn, seat and metrics.

    Yields rows in the order the games were played, which is the order their seeds were spawned.
    """
    for game in played:
        for sample in game.samples:
            yield {
                **run,
                "game": game.index,
                "turn": sample.turn,
                "seat": sample.seat.name,
                **sample.values,
            }


def _engine_seed(stream: np.random.SeedSequence) -> int:
    """An integer seed for the rules engine, which records one in its log.

    The deal takes a generator directly, but a game log carries ``seed: int`` and replay rebuilds
    the game's generator from it — so the engine's stream has to survive as a number.
    """
    return int(stream.generate_state(1, dtype=np.uint32)[0])
