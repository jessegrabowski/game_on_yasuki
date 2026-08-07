import random

import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Action, Legacy, Pass
from yasuki_core.engine.rules.agents import AutoAgent
from yasuki_core.engine.rules.decisions import DecisionResponse, DiscardToHandSize
from yasuki_core.engine.rules.policies import PassPolicy, RandomPolicy
from yasuki_core.engine.rules.projection import GameView
from yasuki_core.engine.rules.log import Act, Answer
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.runner import Controls, play_game, run_game
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import dealt_table, holding, province_card, put_in_play
from tests.yasuki_core.engine.policies import Cheater, RecruitFirst


def _session(seed: int = 1) -> EngineSession:
    return EngineSession.start(dealt_table(), PlayerId.P1, seed=seed)


def _passing(seats=PlayerId) -> dict[PlayerId, Controls]:
    return {seat: Controls(PassPolicy(), AutoAgent()) for seat in seats}


def _random(seed: int) -> dict[PlayerId, Controls]:
    rng = random.Random(seed)
    return {seat: Controls(RandomPolicy(rng), AutoAgent()) for seat in PlayerId}


def test_a_game_stops_at_the_turn_limit():
    session = _session()

    play_game(session, _passing(), turn_limit=6)

    assert session.game.turn == 7  # the first turn past the limit is where it halted


def test_a_turn_limit_of_one_still_plays_a_turn():
    session = _session()

    play_game(session, _passing(), turn_limit=1)

    assert session.game.turn == 2


def test_the_same_seed_and_policies_replay_the_same_game():
    # The determinism the harness rests on, asserted on the log rather than a summary: two games
    # agreeing on their final gold could still have taken different routes there.
    first, second = _session(), _session()

    play_game(first, _random(11), turn_limit=8)
    play_game(second, _random(11), turn_limit=8)

    assert first.log.entries == second.log.entries


def test_different_policy_seeds_produce_different_games():
    first, second = _session(), _session()

    play_game(first, _random(1), turn_limit=8)
    play_game(second, _random(2), turn_limit=8)

    assert first.log.entries != second.log.entries


def test_a_driven_game_replays_to_the_same_state():
    from yasuki_core.engine.rules.log import replay

    session = _session()
    play_game(session, _random(4), turn_limit=8)

    assert replay(session.log) == session.game


def test_a_policy_cannot_take_an_action_it_was_not_offered():
    session = _session()
    controls = {seat: Controls(Cheater(), AutoAgent()) for seat in PlayerId}

    with pytest.raises(RuntimeError, match="not offered"):
        play_game(session, controls, turn_limit=4)


def test_the_driver_stops_when_the_game_ends():
    # The Legacy whiff is the one way a game currently ends on its own: taking it with an empty
    # dynasty deck loses. A driver that only watched the turn counter would play on regardless.
    class AlwaysLegacy:
        def choose(self, view: GameView, actions: list[Action]) -> Action:
            return next((a for a in actions if isinstance(a, Legacy)), actions[0])

    session = _session()
    controls = {seat: Controls(AlwaysLegacy(), AutoAgent()) for seat in PlayerId}

    play_game(session, controls, turn_limit=50)

    assert session.game.game_over
    assert session.game.turn < 50


def test_a_decision_goes_to_the_seat_that_owes_it():
    """Every implemented card raises decisions for the active seat, so nothing yet distinguishes
    "the seat that owes this" from "the seat whose turn it is". Cards where the opponent decides
    are common in the card pool, and routing to the wrong seat would ask the wrong player."""
    session = _session()
    asked: list[tuple[PlayerId, PlayerId]] = []

    class Recording:
        name = "recording"

        def decide(self, request, view: GameView) -> DecisionResponse:
            asked.append((view.viewer, session.game.active))
            return DecisionResponse(())

    session.game.pending = DiscardToHandSize(PlayerId.P2, (), count=0)
    controls = {seat: Controls(PassPolicy(), Recording()) for seat in PlayerId}

    play_game(session, controls, turn_limit=1)

    # Asked P2 while P1 was still the active seat — the two are not the same question.
    assert asked[0] == (PlayerId.P2, PlayerId.P1)


def test_a_policy_chooses_a_recruit_and_an_agent_pays_for_it():
    """The two protocols composing, which is the point of having both: the policy picks the action,
    the agent answers the payment that action raises."""

    session = _session()
    game = session.game
    put_in_play(game, holding("mine", owner=PlayerId.P1, gold_production=4))
    province_card(game, "target", seat=PlayerId.P1, gold_cost=3)
    session.act(PlayerId.P1, Pass())  # Action -> Attack
    session.act(PlayerId.P1, Pass())  # Attack -> Dynasty

    controls = {seat: Controls(RecruitFirst(), AutoAgent()) for seat in PlayerId}
    play_game(session, controls, turn_limit=1)

    recruited = game.table.cards_by_id["target"]

    assert recruited in game.table.battlefield.cards
    assert game.table.cards_by_id["mine"].bowed  # the agent bowed it to pay


class _Turns:
    """Records the turn number and active seat each time a turn begins, and each seat as its turn
    ends."""

    def __init__(self):
        self.seen: list[tuple[int, PlayerId]] = []
        self.ended: list[PlayerId] = []

    def turn_began(self, game) -> None:
        self.seen.append((game.turn, game.active))

    def turn_ended(self, game, seat: PlayerId) -> None:
        self.ended.append(seat)


def test_the_observer_sees_every_turn_once():
    observer = _Turns()

    play_game(_session(), _passing(), turn_limit=4, observer=observer)

    assert observer.seen == [(1, PlayerId.P1), (2, PlayerId.P2), (3, PlayerId.P1), (4, PlayerId.P2)]


def test_a_seats_producers_are_straight_at_the_start_of_its_own_turn():
    """Only the active seat straightens, so a producer bowed to pay stays bowed through the
    opponent's whole turn. A metric sampling a seat's production on every turn would read it as
    halved every other turn; it is canonical only at the start of that seat's own turn."""
    bowed_by_turn: dict[int, bool] = {}

    class Watcher:
        def turn_began(self, game) -> None:
            bowed_by_turn[game.turn] = game.table.cards_by_id["mine"].bowed

        def turn_ended(self, game, seat) -> None:
            pass

    session = _session()
    put_in_play(session.game, holding("mine", owner=PlayerId.P1, gold_production=4))
    province_card(session.game, "target", seat=PlayerId.P1, gold_cost=3)

    controls = {seat: Controls(RecruitFirst(), AutoAgent()) for seat in PlayerId}
    play_game(session, controls, turn_limit=3, observer=Watcher())

    assert bowed_by_turn[1] is False  # P1's turn: straight, nothing spent yet
    assert bowed_by_turn[2] is True  # P2's turn: still bowed from P1 paying
    assert bowed_by_turn[3] is False  # P1's turn again: straightened


def test_a_run_without_an_observer_plays_the_same_game():
    watched, plain = _session(), _session()

    play_game(watched, _random(9), turn_limit=6, observer=_Turns())
    play_game(plain, _random(9), turn_limit=6)

    assert watched.log.entries == plain.log.entries


def test_every_turn_that_began_also_ended():
    observer = _Turns()

    play_game(_session(), _passing(), turn_limit=4, observer=observer)

    # Including the last: the loop exits with that turn begun but not yet closed, so a driver that
    # only fired on the transition would drop the final turn's end-of-turn reading.
    assert observer.ended == [seat for _, seat in observer.seen]


def test_a_turn_ends_with_the_seat_that_played_it_still_untouched():
    """What makes the hook usable: by the time it fires the next turn has begun, but only the new
    active seat straightens, so the finished seat's board is exactly as it left it."""
    ended_bowed: dict[PlayerId, bool] = {}

    class Watcher:
        def turn_began(self, game) -> None:
            pass

        def turn_ended(self, game, seat) -> None:
            ended_bowed[seat] = game.table.cards_by_id["mine"].bowed

    session = _session()
    put_in_play(session.game, holding("mine", owner=PlayerId.P1, gold_production=4))
    province_card(session.game, "target", seat=PlayerId.P1, gold_cost=3)

    controls = {seat: Controls(RecruitFirst(), AutoAgent()) for seat in PlayerId}
    play_game(session, controls, turn_limit=1, observer=Watcher())

    assert ended_bowed[PlayerId.P1] is True  # bowed to pay during the turn it just finished


def test_stepping_yields_each_input_the_engine_accepted():
    """The vocabulary is the log's, so a caller stepping a game sees exactly what the tape records."""
    session = _session()

    steps = list(run_game(session, _passing(), turn_limit=2))

    assert steps == [e for e in session.log.entries if isinstance(e, (Act, Answer))]
    assert all(isinstance(s, (Act, Answer)) for s in steps)


def test_nothing_happens_until_the_iterator_is_advanced():
    # A generator that ran on call would make "build the run, then decide" impossible.
    session = _session()

    run_game(session, _passing(), turn_limit=4)

    assert session.game.turn == 1
    assert session.log.entries == []


def test_a_run_stopped_part_way_leaves_the_game_where_it_stopped():
    """What an interactive caller needs: pause after N steps, inspect, and the board is mid-game
    rather than played out."""
    session = _session()

    steps = run_game(session, _passing(), turn_limit=20)
    for _ in range(3):
        next(steps)
    steps.close()

    assert len(session.log.entries) == 3
    assert not session.game.game_over
    assert (session.game.turn, session.game.phase) == (1, Phase.DYNASTY)


def test_an_abandoned_turn_is_never_closed():
    """Stopping mid-turn leaves that turn unmeasured rather than half-measured, which is what keeps
    a recorder's rows complete."""
    observer = _Turns()

    steps = run_game(_session(), _passing(), turn_limit=20, observer=observer)
    next(steps)
    steps.close()

    assert observer.seen == [(1, PlayerId.P1)]
    assert observer.ended == []


def test_playing_and_stepping_reach_the_same_game():
    played, stepped = _session(), _session()

    play_game(played, _random(7), turn_limit=8)
    for _ in run_game(stepped, _random(7), turn_limit=8):
        pass

    assert played.log.entries == stepped.log.entries
