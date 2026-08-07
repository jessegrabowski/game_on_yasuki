import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.agents import PayingAgent
from yasuki_core.engine.rules.policies import EconomicPolicy, PassPolicy
from yasuki_core.sim.harness import (
    Game,
    per_turn,
    run_games,
    share_reaching,
    summarize,
    summarize_per_turn,
)
from yasuki_core.sim.metrics import potential_gold_production, provinces_cleared
from yasuki_core.sim.recording import Sample

P1, P2 = PlayerId.P1, PlayerId.P2
DECK = "src/yasuki_gui/assets/decks/spider_oni_control.yaml"


def _game(index: int, *values: tuple[int, float], seat: PlayerId = P1) -> Game:
    """A hand-built game, so the aggregation can be checked without playing anything."""
    return Game(
        index=index,
        samples=[Sample(turn=turn, seat=seat, values={"gold": value}) for turn, value in values],
    )


# --- aggregation, as pure functions -------------------------------------------------------------


def test_summarize_describes_the_spread():
    values = list(range(1, 11))  # 1..10

    result = summarize(values)

    assert result.games == 10
    assert result.mean == 5.5
    assert result.median == 5.5
    assert result.low < result.median < result.high


def test_a_single_game_has_no_spread():
    """Percentiles of one point are that point. Interpolating instead would invent a range the run
    never measured."""
    result = summarize([4.0])

    assert (result.games, result.mean, result.median) == (1, 4.0, 4.0)
    assert result.low == result.high == 4.0


def test_summarizing_no_games_is_refused():
    # Returning zeros would read as "the deck produced nothing" rather than "nothing was run".
    with pytest.raises(ValueError, match="empty set of games"):
        summarize([])


def test_per_turn_gathers_one_column_per_turn():
    played = [_game(0, (1, 2.0), (3, 5.0)), _game(1, (1, 4.0), (3, 7.0))]

    assert per_turn(played, P1, "gold") == {1: [2.0, 4.0], 3: [5.0, 7.0]}


def test_a_turn_only_some_games_reached_is_summarized_from_those_games():
    """Games end at different turns, so a late turn thins out. Its summary has to say how many
    games it rests on, or a tail computed from two games reads like the rest."""
    played = [_game(0, (1, 2.0), (3, 6.0)), _game(1, (1, 4.0))]

    summaries = summarize_per_turn(played, P1, "gold")

    assert summaries[1].games == 2
    assert summaries[3].games == 1


def test_the_opponents_turns_are_not_mixed_in():
    played = [_game(0, (1, 2.0)), _game(1, (2, 9.0), seat=P2)]

    assert per_turn(played, P1, "gold") == {1: [2.0]}


def test_share_reaching_counts_games_not_turns():
    """A game that crosses the threshold on several turns still counts once, or a long game would
    outweigh a short one."""
    played = [_game(0, (1, 1.0), (2, 5.0), (3, 5.0)), _game(1, (1, 1.0), (2, 1.0))]

    assert share_reaching(played, P1, "gold", at_least=5.0, by_turn=3) == 0.5


def test_share_reaching_ignores_a_threshold_crossed_too_late():
    played = [_game(0, (1, 1.0), (5, 9.0))]

    assert share_reaching(played, P1, "gold", at_least=9.0, by_turn=3) == 0.0
    assert share_reaching(played, P1, "gold", at_least=9.0, by_turn=5) == 1.0


def test_taking_a_share_of_no_games_is_refused():
    with pytest.raises(ValueError, match="share of no games"):
        share_reaching([], P1, "gold", at_least=1.0, by_turn=1)


# --- the runner, against real games -------------------------------------------------------------


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


def test_lengthening_a_run_leaves_its_earlier_games_untouched():
    """The property spawning buys over deriving seeds in sequence: adding games appends streams
    rather than shifting them, so a longer run still contains the shorter one."""
    kwargs = dict(turn_limit=4, seed=77, metrics={"gold": potential_gold_production})

    short = run_games(DECK, EconomicPolicy(), PayingAgent(), games=2, **kwargs)
    long = run_games(DECK, EconomicPolicy(), PayingAgent(), games=5, **kwargs)

    assert [g.samples for g in long[:2]] == [g.samples for g in short]


def test_the_deal_and_the_engine_draw_from_separate_streams():
    """Two consumers sharing one stream would couple them: how much the engine drew during a game
    would shift the next game's shuffle."""
    from yasuki_core.sim.harness import STREAMS

    assert STREAMS == ("deal", "engine")
    assert len(set(STREAMS)) == len(STREAMS)


def test_the_same_seed_range_replays_the_same_run():
    kwargs = dict(games=3, turn_limit=3, seed=5, metrics={"gold": potential_gold_production})

    first = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)
    second = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)

    assert [g.samples for g in first] == [g.samples for g in second]


def test_different_seeds_produce_different_games():
    """The point of varying the seed. Identical results would mean the shuffle never changed and
    the run measured one game N times."""
    kwargs = dict(games=4, turn_limit=4, metrics={"gold": potential_gold_production})

    one = run_games(DECK, EconomicPolicy(), PayingAgent(), seed=1, **kwargs)
    two = run_games(DECK, EconomicPolicy(), PayingAgent(), seed=500, **kwargs)

    assert [g.samples for g in one] != [g.samples for g in two]


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


def test_a_recruiting_policy_clears_more_provinces_than_one_that_passes():
    """The end-to-end check that the harness measures something a deck-builder would act on."""
    kwargs = dict(games=3, turn_limit=6, seed=20, end_of_turn={"cleared": provinces_cleared})

    passive = run_games(DECK, PassPolicy(), PayingAgent(), **kwargs)
    active = run_games(DECK, EconomicPolicy(), PayingAgent(), **kwargs)

    def total(played):
        return sum(s.values["cleared"] for g in played for s in g.samples)

    assert total(active) > total(passive)
    assert total(passive) == 0


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
