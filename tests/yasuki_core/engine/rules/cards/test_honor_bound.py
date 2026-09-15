from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.effects import Fear, GainHonor
from yasuki_core.engine.rules.triggers import resolve_action_effects
from yasuki_core.engine.rules.vocabulary.actions import KharmicDraw
from yasuki_core.engine.rules.vocabulary.decisions import ChooseInterrupt, DecisionResponse
from yasuki_core.engine.table import ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import pay, personality, put_in_play, two_seat_game
from tests.yasuki_core.engine.rules.test_interrupts import (
    ATTACKER,
    DEFENDER,
    _fear_announced,
    _honor_card,
    _strategy,
)

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
    session.submit(DEFENDER, DecisionResponse(("P2-courage0@courage",)))
    session.submit(DEFENDER, DecisionResponse(("-2 strength",)))

    assert _in_play(session, "guard")
    assert not session.game.table.cards_by_id["guard"].bowed


def test_okura_is_not_offered_against_an_effect_it_does_not_answer():
    game = two_seat_game()
    _honor_card(game.table, "P2-honor0", DEFENDER)
    _strategy(game.table, "okura", "okura_is_released", DEFENDER)
    game.action = KharmicDraw("the-interrupted-action")

    resolve_action_effects(game, [GainHonor(ATTACKER, 2)])

    pending = game.pending
    assert isinstance(pending, ChooseInterrupt)
    assert pending.candidates == ("P2-honor0@honor",)


def test_okura_is_not_offered_when_its_gold_cost_is_out_of_reach():
    game = two_seat_game()
    target = put_in_play(game, personality("guard", owner=DEFENDER, force=2))
    _strategy(game.table, "okura", "okura_is_released", DEFENDER, gold_cost=1)
    game.action = KharmicDraw("the-interrupted-action")

    resolve_action_effects(game, [Fear(2, target.id, ATTACKER)])

    assert game.pending is None
    assert target.bowed


def test_the_okura_game_replays_to_the_same_board():
    session = _fear_announced({}, strategies=(OKURA,))
    session.submit(DEFENDER, DecisionResponse(("okura",)))
    pay(session, DEFENDER)

    rebuilt = replay(session.log)

    assert rebuilt.table.cards_by_id["guard"] not in rebuilt.table.battlefield.cards
    assert rebuilt.pending is None and not rebuilt.stack
