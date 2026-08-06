from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Pass, Recruit
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.rules.policies import PassPolicy
from yasuki_core.engine.runner import Controls, play_game
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.sim.metrics import (
    family_honor,
    potential_gold_production,
    provinces_cleared,
)
from yasuki_core.sim.recording import TurnRecorder

from tests.yasuki_core.engine.builders import (
    dealt_table,
    holding,
    province_card,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _session(p1_production: int = 0, p2_production: int = 0) -> EngineSession:
    table = dealt_table()
    if p1_production:
        put_in_play(table, holding("mine", owner=P1, gold_production=p1_production))
    if p2_production:
        put_in_play(table, holding("theirs", owner=P2, gold_production=p2_production))
    return EngineSession.start(table, P1, seed=1)


def _passing() -> dict[PlayerId, Controls]:
    return {seat: Controls(PassPolicy(), AutoAgent()) for seat in PlayerId}


def test_each_turn_records_the_seat_whose_turn_it_is():
    recorder = TurnRecorder({"gold": potential_gold_production})

    play_game(_session(), _passing(), turn_limit=4, observer=recorder)

    assert [(s.turn, s.seat) for s in recorder.samples] == [(1, P1), (2, P2), (3, P1), (4, P2)]


def test_a_seats_series_holds_only_its_own_turns():
    recorder = TurnRecorder({"gold": potential_gold_production})

    play_game(
        _session(p1_production=5, p2_production=3), _passing(), turn_limit=4, observer=recorder
    )

    assert recorder.series(P1, "gold") == [(1, 5), (3, 5)]
    assert recorder.series(P2, "gold") == [(2, 3), (4, 3)]


def test_a_pass_only_game_holds_its_production_flat():
    # The baseline the plan validates the plumbing against: nothing is spent, so a hand-checkable
    # number repeats. A metric wired to the gold pool would report zero here instead.
    recorder = TurnRecorder({"gold": potential_gold_production})

    play_game(_session(p1_production=7), _passing(), turn_limit=6, observer=recorder)

    assert [value for _, value in recorder.series(P1, "gold")] == [7, 7, 7]


def test_several_metrics_are_recorded_side_by_side():
    recorder = TurnRecorder(
        {
            "gold": potential_gold_production,
            "doubled": lambda g, s: 2 * potential_gold_production(g, s),
        }
    )

    play_game(_session(p1_production=4), _passing(), turn_limit=1, observer=recorder)

    assert recorder.samples[0].values == {"gold": 4, "doubled": 8}


def test_recording_nothing_still_records_the_turns():
    recorder = TurnRecorder({})

    play_game(_session(), _passing(), turn_limit=3, observer=recorder)

    assert [s.turn for s in recorder.samples] == [1, 2, 3]
    assert all(s.values == {} for s in recorder.samples)


def test_a_seats_production_dips_while_the_opponent_plays_and_recovers_on_its_own_turn():
    """The series a deck-builder actually reads, and the shape a naive implementation gets wrong.
    Only the active seat straightens, so a producer P1 bowed to pay is still bowed all through P2's
    turn. Recording every seat every turn would show P1 halved on alternating rows."""
    session = _session(p1_production=6)
    province_card(session.game, "target", seat=P1, gold_cost=4)

    class RecruitFirst:
        def choose(self, view, actions):
            return next((a for a in actions if isinstance(a, Recruit)), Pass())

    recorder = TurnRecorder({"gold": potential_gold_production})
    controls = {seat: Controls(RecruitFirst(), AutoAgent()) for seat in PlayerId}
    play_game(session, controls, turn_limit=3, observer=recorder)

    # P1 is sampled only on its own turns, where its producer has always just straightened.
    assert recorder.series(P1, "gold") == [(1, 6), (3, 6)]


def test_honor_is_recorded_per_seat_across_a_game():
    session = _session()
    ops.set_honor(session.game.table, P1, value=8)
    ops.set_honor(session.game.table, P2, value=3)
    recorder = TurnRecorder({"honor": family_honor})

    play_game(session, _passing(), turn_limit=4, observer=recorder)

    assert recorder.series(P1, "honor") == [(1, 8), (3, 8)]
    assert recorder.series(P2, "honor") == [(2, 3), (4, 3)]


class _RecruitFirst:
    def choose(self, view, actions):
        return next((a for a in actions if isinstance(a, Recruit)), Pass())


def _buyable(gold_cost: int = 2, provinces: int = 2) -> EngineSession:
    """A session where P1 can afford one province card a turn, and the deck can refill behind it."""
    session = _session(p1_production=gold_cost)
    table = session.game.table
    # Priced like the province cards, so one turn's production buys exactly one of them. Free
    # refills would let a turn clear a province repeatedly and the per-turn count would drift up.
    table.decks[DeckKey(P1, Side.DYNASTY)].cards = [
        register(table, holding(f"deck{i}", owner=P1, gold_cost=gold_cost)) for i in range(6)
    ]
    for index in range(provinces):
        province_card(session.game, f"prov{index}", seat=P1, gold_cost=gold_cost, index=index)
    return session


def test_a_cleared_province_reads_zero_at_turn_start_and_one_at_turn_end():
    """Why the metric needs the end-of-turn hook at all. A seat's turn begins by revealing every
    province, so face-down — the mark of one cleared and refilled — cannot exist yet."""
    recorder = TurnRecorder(
        {"cleared_at_start": provinces_cleared},
        end_of_turn={"cleared": provinces_cleared},
    )
    controls = {seat: Controls(_RecruitFirst(), AutoAgent()) for seat in PlayerId}

    play_game(_buyable(), controls, turn_limit=1, observer=recorder)

    assert recorder.series(P1, "cleared_at_start") == [(1, 0)]
    assert recorder.series(P1, "cleared") == [(1, 1)]


def test_the_count_resets_each_turn_rather_than_accumulating():
    """It measures one turn's buying, not the game's. The reveal at the start of each turn is what
    clears it, so a seat that buys one card a turn reads one every turn, never two."""
    recorder = TurnRecorder({}, end_of_turn={"cleared": provinces_cleared})
    controls = {seat: Controls(_RecruitFirst(), AutoAgent()) for seat in PlayerId}

    play_game(_buyable(), controls, turn_limit=5, observer=recorder)

    assert [value for _, value in recorder.series(P1, "cleared")] == [1, 1, 1]


def test_a_seat_that_buys_nothing_clears_no_provinces():
    recorder = TurnRecorder({}, end_of_turn={"cleared": provinces_cleared})

    play_game(_buyable(), _passing(), turn_limit=3, observer=recorder)

    assert [value for _, value in recorder.series(P1, "cleared")] == [0, 0]


def test_start_and_end_metrics_share_one_sample_per_turn():
    recorder = TurnRecorder(
        {"gold": potential_gold_production},
        end_of_turn={"cleared": provinces_cleared},
    )

    play_game(_session(p1_production=4), _passing(), turn_limit=1, observer=recorder)

    assert len(recorder.samples) == 1
    assert recorder.samples[0].values == {"gold": 4, "cleared": 0}


def test_recording_no_end_of_turn_metrics_leaves_the_samples_alone():
    recorder = TurnRecorder({"gold": potential_gold_production})

    play_game(_session(p1_production=3), _passing(), turn_limit=2, observer=recorder)

    assert [s.values for s in recorder.samples] == [{"gold": 3}, {"gold": 0}]
