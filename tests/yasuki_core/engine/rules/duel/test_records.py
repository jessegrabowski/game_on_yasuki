from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.duel.records import DuelRecord

P1, P2 = PlayerId.P1, PlayerId.P2


def test_each_seat_reads_its_own_duelist_and_its_opponent():
    duel = DuelRecord(
        challenger=P1,
        challenged=P2,
        challenger_duelist="kakita",
        challenged_duelist="bayushi",
        source="sanctioned-duel",
    )

    assert duel.duelist_of(P1) == "kakita"
    assert duel.duelist_of(P2) == "bayushi"
    assert duel.opponent_of(P1) is P2
    assert duel.opponent_of(P2) is P1
