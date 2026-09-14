from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import ChooseInterrupt, DecisionResponse
from yasuki_core.engine.table import ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import pay
from tests.yasuki_core.engine.rules.test_interrupts import ATTACKER, DEFENDER, _fear_announced

OKURA = ("okura", "okura_is_released", DEFENDER)


def _in_play(session, card_id: str) -> bool:
    table = session.game.table
    return table.cards_by_id[card_id] in table.battlefield.cards


def test_okura_is_offered_against_a_fear_and_destroys_what_it_bows():
    session = _fear_announced({}, strategies=(OKURA,))
    pending = session.game.pending
    assert isinstance(pending, ChooseInterrupt)
    assert (pending.seat, pending.candidates) == (DEFENDER, ("okura",))

    session.submit(DEFENDER, DecisionResponse(("okura",)))
    pay(session, DEFENDER)

    assert session.game.pending is None
    assert not _in_play(session, "guard")
    discard = session.game.table.zones[ZoneKey(DEFENDER, ZoneRole.FATE_DISCARD)]
    assert [card.id for card in discard.cards] == ["okura"]


def test_okura_leaves_a_target_the_fear_does_not_reach_alone():
    session = _fear_announced({DEFENDER: 1}, strategies=(OKURA,))

    session.submit(DEFENDER, DecisionResponse(("okura",)))
    pay(session, DEFENDER)
    session.submit(DEFENDER, DecisionResponse(("P2-courage0@-2",)))

    assert _in_play(session, "guard")
    assert not session.game.table.cards_by_id["guard"].bowed


def test_okura_is_not_offered_outside_a_fear_window():
    session = _fear_announced({}, strategies=(OKURA,))
    session.submit(DEFENDER, DecisionResponse())

    assert session.game.pending is None
    offered = [
        action
        for seat in (ATTACKER, DEFENDER)
        for action in session.legal_actions(seat)
        if isinstance(action, PlayStrategy)
    ]
    assert offered == []


def test_the_okura_game_replays_to_the_same_board():
    session = _fear_announced({}, strategies=(OKURA,))
    session.submit(DEFENDER, DecisionResponse(("okura",)))
    pay(session, DEFENDER)

    rebuilt = replay(session.log)

    assert rebuilt.table.cards_by_id["guard"] not in rebuilt.table.battlefield.cards
    assert rebuilt.pending is None and not rebuilt.stack
