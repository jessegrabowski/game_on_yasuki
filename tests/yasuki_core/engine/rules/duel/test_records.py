import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.records import DuelOutcome, DuelRecord, DuelStep

P1, P2 = PlayerId.P1, PlayerId.P2


def _duel() -> DuelRecord:
    return DuelRecord(
        challenger=P1,
        challenged=P2,
        challenger_duelist="kakita",
        challenged_duelist="bayushi",
        source="sanctioned-duel",
    )


def test_a_new_duel_stands_at_the_challenge_with_nothing_focused():
    duel = _duel()

    assert duel.step is DuelStep.CHALLENGE
    assert duel.option is None
    assert duel.struck is None
    assert duel.outcome is None
    assert (duel.focuses(P1), duel.focuses(P2)) == (0, 0)


def test_each_seat_reads_its_own_duelist_and_its_opponent():
    duel = _duel()

    assert duel.duelist_of(P1) == "kakita"
    assert duel.duelist_of(P2) == "bayushi"
    assert duel.opponent_of(P1) is P2
    assert duel.opponent_of(P2) is P1


def test_a_seat_the_record_does_not_name_is_refused():
    # Both fields name P1, so P2 is a seat this record is not about: the reads say so rather than
    # answering for the challenged seat by falling through.
    duel = DuelRecord(
        challenger=P1,
        challenged=P1,
        challenger_duelist="kakita",
        challenged_duelist="doji",
        source="sanctioned-duel",
    )

    with pytest.raises(KeyError):
        duel.duelist_of(P2)
    with pytest.raises(KeyError):
        duel.opponent_of(P2)


def test_an_outcome_records_the_totals_and_whether_it_resolved():
    outcome = DuelOutcome(winner=P1, losers=(P2,), totals={P1: 7, P2: 5}, resolved=True)

    assert (outcome.winner, outcome.losers) == (P1, (P2,))
    assert outcome.totals == {P1: 7, P2: 5}
    assert outcome.resolved


def test_an_unresolved_outcome_has_no_winner_and_no_losers():
    outcome = DuelOutcome(winner=None, losers=(), totals={}, resolved=False)

    assert outcome.winner is None
    assert outcome.losers == ()
    assert not outcome.resolved
