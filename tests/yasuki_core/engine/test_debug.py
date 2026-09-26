import json

import pytest

from yasuki_core.engine.debug import (
    ChooseDebugSeat,
    DebugCard,
    DebugGold,
    DebugPersonality,
    PlaceDebugCard,
    apply_debug,
)
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import Answer, Debug, game_log_from_dict, game_log_to_dict
from yasuki_core.engine.rules.vocabulary.decisions import Confirm, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, PersonalityPrint, RingPrint

from tests.yasuki_core.engine.builders import dealt_table, province_card, two_seat_game

P1 = PlayerId.P1
P2 = PlayerId.P2
HAND = ZoneKey(P1, ZoneRole.HAND)
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)
A_STRATEGY = ActionPrint(name="Debug Strategy", side=Side.FATE)
A_PERSONALITY = PersonalityPrint(name="Debug Bushi", side=Side.DYNASTY, force=2, chi=2)


def test_debug_gold_lands_in_the_pool():
    game = two_seat_game()

    apply_debug(game, DebugGold(P1, 100))

    assert game.gold[P1] == 100


def test_a_fate_debug_card_lands_in_the_hand_as_a_real_card():
    game = two_seat_game()

    apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY))

    card = game.table.cards_by_id["dbg-1"]
    assert card in game.table.zones[HAND].cards
    assert card.owner is P1
    assert not card.is_token
    assert card.printed.name == "Debug Strategy"


def test_a_dynasty_debug_card_asks_which_province_card_it_displaces():
    state = dealt_table()
    province_card(state, "old", seat=P1)
    session = EngineSession.start(state, P1)

    session.debug(DebugCard(P1, "dbg-1", A_PERSONALITY))

    pending = session.game.pending
    assert isinstance(pending, PlaceDebugCard)
    assert pending.seat is P1
    assert "old" in pending.candidates
    assert pending.accepts(DecisionResponse(("old",)))
    assert not pending.accepts(DecisionResponse(("old", "old")))
    assert not pending.accepts(DecisionResponse(("dbg-1",)))


def test_placing_a_dynasty_debug_card_discards_what_was_there_and_lands_face_up():
    state = dealt_table()
    province_card(state, "old", seat=P1)
    session = EngineSession.start(state, P1)
    session.debug(DebugCard(P1, "dbg-1", A_PERSONALITY))

    session.submit(P1, DecisionResponse(("old",)))

    assert session.game.pending is None
    assert [card.id for card in session.game.table.zones[FIRST].cards] == ["dbg-1"]
    assert session.game.table.cards_by_id["dbg-1"].face_up
    assert session.game.round.priority is P1
    discard = session.game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert "old" in {card.id for card in discard}
    assert [type(entry) for entry in session.log.entries] == [Debug, Answer]
    assert session.log.replay() == session.game


def test_a_debug_personality_asks_which_player_gets_it():
    session = EngineSession.start(dealt_table(), P1)

    session.debug(DebugPersonality(P1, "dbg-1", A_PERSONALITY))

    pending = session.game.pending
    assert isinstance(pending, ChooseDebugSeat)
    assert pending.seat is P1
    assert pending.candidates == ("P1", "P2")
    assert pending.accepts(DecisionResponse(("P2",)))
    assert not pending.accepts(DecisionResponse(("P1", "P2")))
    assert "dbg-1" not in session.game.table.cards_by_id


def test_a_debug_personality_enters_play_under_the_chosen_player():
    session = EngineSession.start(dealt_table(), P1)
    session.debug(DebugPersonality(P1, "dbg-1", A_PERSONALITY))

    session.submit(P1, DecisionResponse(("P2",)))

    card = session.game.table.cards_by_id["dbg-1"]
    assert session.game.pending is None
    assert card.owner is P2
    assert card.face_up
    assert not card.bowed
    assert card in session.game.table.battlefield.cards
    assert session.game.round.priority is P1
    assert [type(entry) for entry in session.log.entries] == [Debug, Answer]
    assert session.log.replay() == session.game
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


def test_a_debug_personality_refuses_a_print_that_is_not_a_personality():
    game = two_seat_game()

    with pytest.raises(ValueError, match="not a Personality"):
        apply_debug(game, DebugPersonality(P1, "dbg-1", A_STRATEGY))


def test_a_debug_step_is_refused_while_a_decision_is_pending():
    game = two_seat_game()
    game.pending = Confirm(P1, (), "Really?", "probe")

    with pytest.raises(RuntimeError, match="pending"):
        apply_debug(game, DebugGold(P1, 1))


def test_a_debug_card_refuses_an_id_already_on_the_table():
    game = two_seat_game()
    apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY))

    with pytest.raises(ValueError, match="already"):
        apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY))


def test_a_dynasty_debug_card_refuses_a_seat_with_no_province_card():
    game = two_seat_game()

    with pytest.raises(ValueError, match="no Province card"):
        apply_debug(game, DebugCard(P1, "dbg-1", A_PERSONALITY))


def test_a_refused_debug_step_leaves_the_tape_untouched():
    session = EngineSession.start(dealt_table(), P1)
    session.debug(DebugCard(P1, "dbg-1", A_STRATEGY))

    with pytest.raises(ValueError, match="already"):
        session.debug(DebugCard(P1, "dbg-1", A_STRATEGY))

    assert [type(entry) for entry in session.log.entries] == [Debug]
    assert session.log.replay() == session.game


def test_a_tape_with_an_unknown_debug_kind_is_refused():
    session = EngineSession.start(dealt_table(), P1)
    session.debug(DebugGold(P1, 100))
    taped = game_log_to_dict(session.log)
    taped["entries"][0]["step"]["kind"] = "token"

    with pytest.raises(ValueError, match="token"):
        game_log_from_dict(taped)


def test_debug_steps_are_taped_replay_and_round_trip():
    session = EngineSession.start(dealt_table(), P1)

    session.debug(DebugGold(P1, 100))
    session.debug(DebugCard(P1, "dbg-1", A_STRATEGY))

    assert [type(entry) for entry in session.log.entries] == [Debug, Debug]
    assert session.log.replay() == session.game
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game


def test_a_debug_ring_spawned_into_a_hand_that_fulfills_its_condition_is_offered_outside_any_action():
    # Ring of the Void watches for as many Fate cards in play as in hand: none and none here.
    session = EngineSession.start(TableState.empty_two_seat(), P1)
    void = RingPrint(name="Ring of the Void", side=Side.FATE, printed_id="ring_of_the_void")

    session.debug(DebugCard(P1, "void", void))

    pending = session.game.pending
    assert isinstance(pending, Confirm) and pending.seat is P1 and "void" in pending.candidates
    session.submit(P1, DecisionResponse(()))
    assert session.game.round.priority is P1
    assert session.log.replay() == session.game
