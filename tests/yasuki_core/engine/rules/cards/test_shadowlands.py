from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.stats.ongoing_grants import named_duel_stat
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import FatePrint
from yasuki_core.game_pieces.constants import Side

from tests.yasuki_core.engine.builders import combat_segment, personality

P1, P2 = PlayerId.P1, PlayerId.P2


def _test_of_might_in_combat(*, mine_force: int, theirs_force: int) -> EngineSession:
    """The Combat Segment of P1's attack with Test of Might in P1's hand, one Personality each at
    the battlefield. Chi is left at the builder's default, so a duel on the wrong stat ties."""
    cards = [
        personality("mine", force=mine_force),
        personality("theirs", owner=P2, force=theirs_force),
    ]
    strategy = L5RCard.of(
        FatePrint,
        id="might",
        name="Test of Might",
        side=Side.FATE,
        owner=P1,
        printed_id="test_of_might",
        focus=2,
    )
    return combat_segment(cards, {"mine": 0}, {"theirs": 0}, in_hand=[strategy])


def _play_it(session: EngineSession) -> EngineSession:
    session.act(P1, PlayStrategy("might"))
    session.submit(P1, DecisionResponse(("mine",)))
    session.submit(P1, DecisionResponse(("theirs",)))
    return session


def test_test_of_might_duels_on_force_honoring_the_winner_and_bowing_the_loser():
    # Equal Chi, so a duel on the arc's default stat ties and bows both instead.
    session = _play_it(_test_of_might_in_combat(mine_force=5, theirs_force=1))

    assert session.game.duel.outcome.totals == {P1: 5, P2: 1}
    assert session.game.table.seats[P1].honor == 3
    assert session.game.table.cards_by_id["theirs"].bowed
    assert not session.game.table.cards_by_id["mine"].bowed


def test_the_enemys_controller_is_honored_when_the_enemy_wins():
    # "The winner's controller gains 3 Honor" names the winner, which can be the other seat.
    session = _play_it(_test_of_might_in_combat(mine_force=1, theirs_force=5))

    assert session.game.table.seats[P2].honor == 3
    assert session.game.table.seats[P1].honor == 0
    assert session.game.table.cards_by_id["mine"].bowed


def test_a_tie_bows_both_personalities_and_honors_nobody():
    session = _play_it(_test_of_might_in_combat(mine_force=3, theirs_force=3))

    outcome = session.game.duel.outcome
    assert outcome.winners == ()
    assert set(outcome.losers) == {P1, P2}
    assert session.game.table.seats[P1].honor == 0
    assert session.game.table.cards_by_id["mine"].bowed
    assert session.game.table.cards_by_id["theirs"].bowed


def test_the_enemy_is_picked_after_your_own_duelist():
    # One ability takes one target, so the enemy is a choice of its own rather than a second target.
    session = _test_of_might_in_combat(mine_force=5, theirs_force=1)

    session.act(P1, PlayStrategy("might"))
    session.submit(P1, DecisionResponse(("mine",)))

    pending = session.game.pending
    assert isinstance(pending, ChooseCards)
    assert pending.candidates == ("theirs",)
    assert pending.resolver_context == ("might",)


def test_no_duel_happens_when_the_last_enemy_leaves_after_the_announcement():
    # The enemy pool is recomputed when the first target is answered, which is after the board could
    # have changed. A `Choose` of one from none would pend with no answer that satisfies it.
    session = _test_of_might_in_combat(mine_force=5, theirs_force=1)

    session.act(P1, PlayStrategy("might"))
    ops.remove_card(session.game.table, session.game.table.cards_by_id["theirs"])
    session.submit(P1, DecisionResponse(("mine",)))

    assert session.game.pending is None
    assert session.game.duel is None


def test_the_duel_stat_does_not_outlive_the_duel():
    session = _play_it(_test_of_might_in_combat(mine_force=5, theirs_force=1))

    assert named_duel_stat(session.game, "mine") is None
    assert named_duel_stat(session.game, "theirs") is None


def test_a_bowed_personality_cannot_be_the_one_performing():
    session = _test_of_might_in_combat(mine_force=5, theirs_force=1)
    session.game.table.cards_by_id["mine"].bow()

    assert PlayStrategy("might") not in session.legal_actions(P1)


def test_test_of_might_replays_to_the_same_board():
    session = _play_it(_test_of_might_in_combat(mine_force=5, theirs_force=1))

    assert replay(session.log).table == session.game.table
