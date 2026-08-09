import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import psycopg

from yasuki_core.engine.rules.agents import Agent, PayingAgent
from yasuki_core.engine.rules.policies import POLICIES, make_policy
from yasuki_core.sim.harness import run_games, sample_rows, write_rows
from yasuki_core.sim.metrics import (
    Metric,
    empty_provinces,
    family_honor,
    potential_gold_production,
    province_clearance,
    provinces_cleared,
    provinces_held,
)

# The policy a run uses when none is named. A result quoted without its policy compares against
# nothing, so the name rides along in the output either way.
DEFAULT_POLICY = "economic"

# Hands dealt per turn to estimate the clearance probability. Its standard error is at worst one
# point at this count, which is finer than the differences between decks the runs are asked about.
CLEARANCE_SAMPLES = 500


def turn_start_metrics(seed: int) -> dict[str, Metric]:
    """The metrics read as each turn begins, when the seat has just straightened and its board is
    canonical. Takes the run's seed because clearance is estimated by sampling, and a metric
    reaching for the global random stream would make one run depend on the last."""
    return {
        "gold": potential_gold_production,
        "honor": family_honor,
        "provinces": provinces_held,
        "clearance": province_clearance(np.random.default_rng(seed), samples=CLEARANCE_SAMPLES),
    }


# Sampled as each turn ends, where a count of what the turn did is what matters.
TURN_END_METRICS: dict[str, Metric] = {
    "cleared": provinces_cleared,
    "empty": empty_provinces,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Play a decklist against itself many times and write the per-turn rows out"
    )
    parser.add_argument("deck", type=Path, help="the decklist both seats play")
    parser.add_argument("--out", type=Path, required=True, help="the .parquet or .csv to write")
    parser.add_argument("--games", type=int, default=100, help="games per policy. Default 100")
    parser.add_argument("--turns", type=int, default=10, help="last turn of each game. Default 10")
    parser.add_argument("--seed", type=int, default=0, help="root seed for every stream. Default 0")
    parser.add_argument(
        "--policy",
        action="append",
        choices=sorted(POLICIES),
        metavar="NAME",
        help=(
            "policy to run, repeatable to sweep several into one table "
            f"(one of: {', '.join(sorted(POLICIES))}). Default {DEFAULT_POLICY}"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the simulation described by ``argv`` and write its rows. Return a process exit code."""
    args = build_parser().parse_args(argv)
    # Not argparse's own default: with action="append" a default list is appended to rather
    # than replaced, so naming one policy would silently run two.
    policies = args.policy or [DEFAULT_POLICY]

    rows: list[dict[str, object]] = []
    for name in policies:
        policy = make_policy(name)
        # A policy that answers its own decisions is passed as both, so the cards it chooses over
        # are the cards it acts on; the rest lean on the generic paying agent.
        agent = policy if isinstance(policy, Agent) else PayingAgent()
        try:
            played = run_games(
                args.deck,
                policy,
                agent,
                games=args.games,
                turn_limit=args.turns,
                seed=args.seed,
                metrics=turn_start_metrics(args.seed),
                end_of_turn=TURN_END_METRICS,
            )
        except psycopg.OperationalError as exc:
            # The deck loader reads the card database; a psycopg traceback tells someone running a
            # simulation nothing. Every other failure is a bug and keeps its traceback.
            print(
                f"cannot reach the card database, which {args.deck} must be built from: {exc}",
                file=sys.stderr,
            )
            return 1
        except FileNotFoundError as exc:
            print(f"no such decklist: {exc.filename}", file=sys.stderr)
            return 1
        # Every policy's rows carry the same seed, so a sweep compares them over the same deals.
        rows.extend(
            sample_rows(
                played,
                deck=args.deck.stem,
                policy=name,
                seed=args.seed,
                games=args.games,
                turns=args.turns,
            )
        )

    write_rows(args.out, rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
