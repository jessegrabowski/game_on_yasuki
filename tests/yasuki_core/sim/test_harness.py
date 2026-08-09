import csv

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.agents import PayingAgent
from yasuki_core.engine.rules.policies import EconomicPolicy, PassPolicy
from yasuki_core.sim.harness import Game, run_games, sample_rows, write_csv, write_rows
from yasuki_core.sim.metrics import potential_gold_production, provinces_cleared
from yasuki_core.sim.recording import Sample

from tests.yasuki_core.db_guard import requires_db

P1, P2 = PlayerId.P1, PlayerId.P2
DECK = "src/yasuki_gui/assets/decks/spider_oni_control.yaml"


def _game(index: int, *values: tuple[int, float], seat: PlayerId = P1) -> Game:
    """A hand-built game, so the aggregation can be checked without playing anything."""
    return Game(
        index=index,
        samples=[Sample(turn=turn, seat=seat, values={"gold": value}) for turn, value in values],
    )


# --- writing the data out ------------------------------------------------------------------------


def test_rows_carry_the_run_and_the_turn():
    played = [_game(0, (1, 2.0), (2, 5.0))]

    rows = list(sample_rows(played, deck="spider", policy="economic", seed=3))

    assert rows == [
        {
            "deck": "spider",
            "policy": "economic",
            "seed": 3,
            "game": 0,
            "turn": 1,
            "seat": "P1",
            "gold": 2.0,
        },
        {
            "deck": "spider",
            "policy": "economic",
            "seed": 3,
            "game": 0,
            "turn": 2,
            "seat": "P1",
            "gold": 5.0,
        },
    ]


def test_provenance_repeats_on_every_row_so_runs_concatenate():
    """Two runs written to one table have to stay tellable apart, which a header comment would not
    survive once the files are stacked."""
    first = list(sample_rows([_game(0, (1, 1.0))], seed=1))
    second = list(sample_rows([_game(0, (1, 1.0))], seed=2))

    assert {row["seed"] for row in first + second} == {1, 2}


def test_provenance_that_would_be_overwritten_is_refused():
    """Silently keeping the turn's value and dropping the provenance would put a column in the
    table that means one thing on some rows and another on the rest."""
    played = [_game(0, (1, 2.0))]

    with pytest.raises(ValueError, match="turn"):
        list(sample_rows(played, turn=99))
    with pytest.raises(ValueError, match="gold"):
        list(sample_rows(played, gold=0.0))


def test_a_provenance_name_no_row_uses_is_allowed():
    assert list(sample_rows([_game(0, (1, 2.0))], turns=99))[0]["turns"] == 99


def test_both_seats_are_written_not_just_one():
    played = [_game(0, (1, 2.0)), _game(1, (2, 9.0), seat=P2)]

    assert {row["seat"] for row in sample_rows(played)} == {"P1", "P2"}


def test_written_csv_round_trips(tmp_path):
    played = [_game(0, (1, 2.0), (2, 5.0)), _game(1, (1, 3.0))]
    path = tmp_path / "run.csv"

    write_csv(path, played, deck="spider", seed=3)

    with path.open() as handle:
        rows = list(csv.DictReader(handle))
    assert [r["game"] for r in rows] == ["0", "0", "1"]
    assert [r["gold"] for r in rows] == ["2.0", "5.0", "3.0"]
    assert {r["deck"] for r in rows} == {"spider"}


def test_writing_a_run_that_recorded_nothing_is_refused(tmp_path):
    # A header with no rows reads as "the deck did nothing" rather than "nothing was recorded".
    with pytest.raises(ValueError, match="nothing to write"):
        write_csv(tmp_path / "empty.csv", [], seed=1)


@pytest.mark.parametrize(
    "name, reader",
    [("run.csv", "csv"), ("run.parquet", "parquet"), ("run", "parquet")],
    ids=["csv suffix", "parquet suffix", "no suffix"],
)
def test_the_suffix_picks_the_format_and_parquet_is_the_default(tmp_path, name, reader):
    # Parquet unless the path says .csv, so a run keeps its column types unless someone opts out.
    # The no-suffix case is the one that decides which way the rule points.
    pq = pytest.importorskip("pyarrow.parquet")
    rows = list(sample_rows([_game(0, (1, 2.0))], deck="spider"))
    path = tmp_path / name

    write_rows(path, rows)

    if reader == "csv":
        with path.open() as handle:
            assert [r["gold"] for r in csv.DictReader(handle)] == ["2.0"]
    else:
        assert pq.read_table(path).column("gold").to_pylist() == [2.0]


def test_writing_no_rows_is_refused_whatever_the_format(tmp_path):
    # Same reason as the CSV writer: a file carrying only a schema reads as a run that did nothing.
    with pytest.raises(ValueError, match="nothing to write"):
        write_rows(tmp_path / "empty.parquet", [])


# --- the runner, against real games -------------------------------------------------------------


@requires_db
def test_each_game_is_indexed_by_its_position_in_the_run():
    played = run_games(
        DECK,
        PassPolicy(),
        PayingAgent(),
        games=3,
        turn_limit=2,
        seed=100,
        metrics={"gold": potential_gold_production},
    )

    assert [game.index for game in played] == [0, 1, 2]


@requires_db
def test_lengthening_a_run_leaves_its_earlier_games_untouched():
    """The property spawning buys over deriving seeds in sequence: adding games appends streams
    rather than shifting them, so a longer run still contains the shorter one."""
    kwargs = dict(turn_limit=4, seed=77, metrics={"gold": potential_gold_production})

    short = run_games(DECK, EconomicPolicy(), PayingAgent(), games=2, **kwargs)
    long = run_games(DECK, EconomicPolicy(), PayingAgent(), games=5, **kwargs)

    assert [g.samples for g in long[:2]] == [g.samples for g in short]


@requires_db
def test_the_same_seed_range_replays_the_same_run():
    kwargs = dict(games=3, turn_limit=3, seed=5, metrics={"gold": potential_gold_production})

    first = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)
    second = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)

    assert [g.samples for g in first] == [g.samples for g in second]


@requires_db
def test_different_seeds_produce_different_games():
    """The point of varying the seed. Identical results would mean the shuffle never changed and
    the run measured one game N times."""
    kwargs = dict(games=4, turn_limit=4, metrics={"gold": potential_gold_production})

    one = run_games(DECK, EconomicPolicy(), PayingAgent(), seed=1, **kwargs)
    two = run_games(DECK, EconomicPolicy(), PayingAgent(), seed=500, **kwargs)

    assert [g.samples for g in one] != [g.samples for g in two]


@requires_db
def test_a_run_records_the_metrics_it_was_given():
    played = run_games(
        DECK,
        EconomicPolicy(),
        PayingAgent(),
        games=2,
        turn_limit=3,
        seed=9,
        end_of_turn={"cleared": provinces_cleared},
        actions={"bought": Recruit},
    )

    assert played
    for game in played:
        assert game.samples
        assert all(set(s.values) == {"cleared", "bought"} for s in game.samples)
    # Recording the names is half of it; a run where nothing was ever bought would leave the action
    # counting unexercised and this test green.
    assert any(s.values["bought"] for game in played for s in game.samples)


@requires_db
def test_a_recruiting_policy_clears_more_provinces_than_one_that_passes():
    """The end-to-end check that the harness measures something a deck-builder would act on."""
    kwargs = dict(games=3, turn_limit=6, seed=20, end_of_turn={"cleared": provinces_cleared})

    passive = run_games(DECK, PassPolicy(), PayingAgent(), **kwargs)
    active = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)

    def total(played):
        return sum(s.values["cleared"] for g in played for s in g.samples)

    assert total(active) > total(passive)
    assert total(passive) == 0


@requires_db
def test_games_within_a_run_differ_from_each_other():
    """A run whose games are all identical reports a point mass dressed as a distribution. This is
    the property spawning exists to provide, and the one a shared stream would destroy."""
    played = run_games(
        DECK,
        EconomicPolicy(),
        PayingAgent(),
        games=4,
        turn_limit=5,
        seed=3,
        metrics={"gold": potential_gold_production},
    )

    shapes = {
        tuple((s.turn, s.seat, tuple(sorted(s.values.items()))) for s in game.samples)
        for game in played
    }

    assert len(shapes) > 1
