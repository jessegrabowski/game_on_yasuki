import psycopg
import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.policies import EconomicCyclePolicy, EconomicPolicy
from yasuki_core.sim import cli
from yasuki_core.sim.harness import Game
from yasuki_core.sim.recording import Sample

DECK = "src/yasuki_gui/assets/decks/spider_oni_control.yaml"


def _fake_run(calls, games=1):
    """Stand in for ``run_games``, recording how it was called and returning one sampled turn."""

    def run(deck_path, policy, agent, **kwargs):
        calls.append({"deck": deck_path, "policy": policy, "agent": agent, **kwargs})
        return [
            Game(index=index, samples=[Sample(turn=1, seat=PlayerId.P1, values={"gold": 3})])
            for index in range(games)
        ]

    return run


def test_the_flags_reach_the_run(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "run_games", _fake_run(calls))
    out = tmp_path / "run.parquet"

    assert cli.main([DECK, "--out", str(out), "--games", "7", "--turns", "3", "--seed", "11"]) == 0

    assert len(calls) == 1
    assert calls[0]["games"] == 7 and calls[0]["turn_limit"] == 3 and calls[0]["seed"] == 11
    assert isinstance(calls[0]["policy"], EconomicPolicy)  # the default when none is named


def test_a_repeated_policy_flag_sweeps_into_one_table(monkeypatch, tmp_path):
    # The point of the sweep: one file, told apart by a column, over the same deals — so the
    # policies are comparable rather than each run being its own incomparable file.
    calls = []
    monkeypatch.setattr(cli, "run_games", _fake_run(calls, games=2))
    out = tmp_path / "run.csv"

    cli.main([DECK, "--out", str(out), "--policy", "economic", "--policy", "economic-cycle"])

    assert [type(call["policy"]) for call in calls] == [EconomicPolicy, EconomicCyclePolicy]
    assert {call["seed"] for call in calls} == {0}  # both policies see the same deals
    written = out.read_text().splitlines()
    assert len(written) == 5  # a header plus one row per game per policy
    assert [line.split(",")[1] for line in written[1:]] == ["economic"] * 2 + ["economic-cycle"] * 2


def test_a_policy_that_answers_its_own_decisions_is_used_as_its_own_agent(monkeypatch, tmp_path):
    # EconomicCyclePolicy decides which cards it cycles as well as choosing to cycle. Handing the
    # generic agent those decisions would put back a different set than the one it chose over.
    calls = []
    monkeypatch.setattr(cli, "run_games", _fake_run(calls))

    cli.main([DECK, "--out", str(tmp_path / "run.parquet"), "--policy", "economic-cycle"])

    assert calls[0]["agent"] is calls[0]["policy"]


def test_an_unreachable_database_is_reported_rather_than_traced(monkeypatch, tmp_path, capsys):
    def unreachable(*args, **kwargs):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(cli, "run_games", unreachable)

    assert cli.main([DECK, "--out", str(tmp_path / "run.parquet")]) == 1
    # On stderr, so a shell capturing the run's output does not swallow the reason it failed.
    assert "cannot reach the card database" in capsys.readouterr().err


def test_a_bug_in_the_run_keeps_its_traceback(monkeypatch, tmp_path):
    # The database message must not become a catch-all: a failure that is not about reaching the
    # database is a defect, and swallowing it into a tidy one-liner hides where it came from.
    def broken(*args, **kwargs):
        raise ZeroDivisionError("a real bug")

    monkeypatch.setattr(cli, "run_games", broken)

    with pytest.raises(ZeroDivisionError):
        cli.main([DECK, "--out", str(tmp_path / "run.parquet")])


def test_an_unknown_policy_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(SystemExit):
        cli.main([DECK, "--out", str(tmp_path / "run.parquet"), "--policy", "nonesuch"])


@pytest.mark.slow
def test_a_written_run_reads_back_with_its_provenance(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    out = tmp_path / "run.parquet"

    assert cli.main([DECK, "--out", str(out), "--games", "2", "--turns", "2"]) == 0

    table = pq.read_table(out)
    assert table.num_rows > 0
    # Provenance first, so a table concatenated with another can be told apart later.
    assert table.column_names[:4] == ["deck", "policy", "seed", "turns"]
    assert set(table.column("policy").to_pylist()) == {"economic"}
    assert set(table.column("deck").to_pylist()) == {"spider_oni_control"}
