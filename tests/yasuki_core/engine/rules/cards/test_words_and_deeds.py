from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.words_and_deeds import MILITIA_RECRUIT
from yasuki_core.engine.rules.decisions import ChoosePayment, Confirm, DecisionResponse
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    holding,
    personality,
    put_in_play,
    stronghold,
    token_template,
    two_seat_game,
)

P1 = PlayerId.P1


# --- Militia Training Ground ---


def _militia_game(*, gold_production: int = 5):
    """The Grounds in play beside a Personality, under a Stronghold making ``gold_production``."""
    game = two_seat_game()
    token_template(game, MILITIA_RECRUIT, name="Militia Recruit", card_type="Follower", force=0)
    put_in_play(game, stronghold(P1, gold_production=gold_production))
    put_in_play(game, holding("grounds", printed_id="militia_training_ground", name="the Grounds"))
    put_in_play(game, personality("hero", force=2, chi=3))
    return EngineSession.start(game.table, P1)


def test_the_grounds_ask_which_way_to_pay_when_both_are_open():
    session = _militia_game()

    session.act(P1, ActivateAbility("grounds"))

    assert isinstance(session.game.pending, Confirm)
    assert session.game.pending.question == "Pay 2 gold instead of bowing the Grounds?"


def test_bowing_the_grounds_equips_a_follower_and_spends_no_gold():
    session = _militia_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(()))  # no: bow instead
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    assert attachments_of(game, game.table.cards_by_id["hero"])[0].name == "Militia Recruit"
    assert game.table.cards_by_id["grounds"].bowed is True
    assert game.gold[P1] == 0


def test_paying_the_gold_leaves_the_grounds_standing():
    session = _militia_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("grounds",)))  # yes: pay instead
    assert isinstance(session.game.pending, ChoosePayment)
    session.submit(P1, DecisionResponse(("P1-SH",)))  # bow the Stronghold for the gold
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    assert attachments_of(game, game.table.cards_by_id["hero"])[0].name == "Militia Recruit"
    assert game.table.cards_by_id["grounds"].bowed is False
    assert game.gold[P1] == 3  # the Stronghold made five and the Grounds took two


def test_a_bowed_grounds_is_charged_the_gold_without_being_asked():
    """With one way left to pay, the card takes it rather than putting a settled question."""
    session = _militia_game()
    session.game.table.cards_by_id["grounds"].bow()

    session.act(P1, ActivateAbility("grounds"))

    assert isinstance(session.game.pending, ChoosePayment)
    assert session.game.pending.amount == 2


def test_a_bowed_grounds_with_no_gold_in_reach_is_not_offered_at_all():
    session = _militia_game(gold_production=1)
    session.game.table.cards_by_id["grounds"].bow()

    assert ActivateAbility("grounds") not in session.legal_actions(P1)


def test_the_grounds_replay_to_the_same_board():
    session = _militia_game()
    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("grounds",)))
    session.submit(P1, DecisionResponse(("P1-SH",)))
    session.submit(P1, DecisionResponse(("hero",)))

    assert replay(session.log).table == session.game.table
