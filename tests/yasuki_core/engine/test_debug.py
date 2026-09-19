import json

import pytest

from yasuki_core.engine.debug import DebugCard, DebugGold, apply_debug
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import Debug, game_log_from_dict, game_log_to_dict
from yasuki_core.engine.rules.vocabulary.decisions import Confirm
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, HoldingPrint, PersonalityPrint

from tests.yasuki_core.engine.builders import dealt_table, province_card, two_seat_game

P1 = PlayerId.P1
HAND = ZoneKey(P1, ZoneRole.HAND)
FIRST = ZoneKey(P1, ZoneRole.PROVINCE, 0)
A_HOLDING = HoldingPrint(name="Debug Farm", side=Side.DYNASTY, gold_production=2)
A_STRATEGY = ActionPrint(name="Debug Strategy", side=Side.FATE)
A_PERSONALITY = PersonalityPrint(name="Debug Bushi", side=Side.DYNASTY, force=2, chi=2)


def test_debug_gold_lands_in_the_pool():
    game = two_seat_game()

    apply_debug(game, DebugGold(P1, 100))

    assert game.gold[P1] == 100


def test_a_debug_card_lands_in_the_hand_as_a_real_card():
    game = two_seat_game()

    apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY, HAND))

    card = game.table.cards_by_id["dbg-1"]
    assert card in game.table.zones[HAND].cards
    assert card.owner is P1 and not card.is_token
    assert card.printed.name == "Debug Strategy"


def test_a_debug_card_in_a_province_discards_what_was_there_and_lands_face_up():
    state = dealt_table()
    province_card(state, "old", seat=P1)
    game = EngineSession.start(state, P1).game

    apply_debug(game, DebugCard(P1, "dbg-1", A_PERSONALITY, FIRST))

    assert [card.id for card in game.table.zones[FIRST].cards] == ["dbg-1"]
    assert game.table.cards_by_id["dbg-1"].face_up
    discard = game.table.zones[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards
    assert "old" in {card.id for card in discard}


def test_a_debug_step_is_refused_while_a_decision_is_pending():
    game = two_seat_game()
    game.pending = Confirm(P1, (), "Really?", "probe")

    with pytest.raises(RuntimeError, match="pending"):
        apply_debug(game, DebugGold(P1, 1))


def test_a_debug_card_refuses_an_id_already_on_the_table():
    game = two_seat_game()
    apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY, HAND))

    with pytest.raises(ValueError, match="already"):
        apply_debug(game, DebugCard(P1, "dbg-1", A_STRATEGY, HAND))


def test_a_debug_card_refuses_the_wrong_side_for_the_zone():
    """A hand holds Fate cards and a Province holds Dynasty cards, and the zones refuse the rest
    silently, which would leave the card registered and nowhere."""
    game = two_seat_game()

    with pytest.raises(ValueError, match="cannot land"):
        apply_debug(game, DebugCard(P1, "dbg-1", A_HOLDING, HAND))


def test_a_debug_card_refuses_a_pile():
    game = two_seat_game()

    with pytest.raises(ValueError, match="hand or a Province"):
        apply_debug(game, DebugCard(P1, "dbg-1", A_HOLDING, ZoneKey(P1, ZoneRole.FATE_DISCARD)))


def test_debug_steps_are_taped_replay_and_round_trip():
    """A step outside the tape would vanish on the next cancel, which rebuilds the game from it."""
    session = EngineSession.start(dealt_table(), P1)

    session.debug(DebugGold(P1, 100))
    session.debug(DebugCard(P1, "dbg-1", A_STRATEGY, HAND))

    assert [type(entry) for entry in session.log.entries] == [Debug, Debug]
    assert session.log.replay() == session.game
    restored = game_log_from_dict(json.loads(json.dumps(game_log_to_dict(session.log))))
    assert restored.replay() == session.game
