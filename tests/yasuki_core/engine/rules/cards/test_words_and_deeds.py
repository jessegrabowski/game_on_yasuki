from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import Bow
from yasuki_core.engine.rules.triggers import resolve_action_effects
from yasuki_core.engine.rules.turn.structure import RoundKind
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility, Pass, PlayInterrupt
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.words_and_deeds import MILITIA_RECRUIT
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseInterruptTarget,
    ChoosePayment,
    Confirm,
    DecisionResponse,
)
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    holding,
    pay,
    personality,
    put_in_play,
    stronghold,
    token_template,
    two_seat_game,
)
from tests.yasuki_core.engine.rules.test_interrupts import _strategy

P1, P2 = PlayerId.P1, PlayerId.P2


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
    pay(session, P1)  # bow the Stronghold for the gold
    session.submit(P1, DecisionResponse(("hero",)))

    game = session.game
    assert attachments_of(game, game.table.cards_by_id["hero"])[0].name == "Militia Recruit"
    assert game.table.cards_by_id["grounds"].bowed is False
    assert game.gold[P1] == 3  # the Stronghold made five and the Grounds took two


def test_a_bowed_grounds_is_not_offered_even_with_the_gold_to_pay():
    """Abilities on a bowed card cannot be used (CR, Using Abilities), so having another way to
    pay the cost does not reach the ability. A Holding bowed for its gold has spent its turn."""
    session = _militia_game()
    session.game.table.cards_by_id["grounds"].bow()
    session.game.add_gold(P1, 2)

    assert ActivateAbility("grounds") not in session.legal_actions(P1)


def test_a_bowed_grounds_with_no_gold_in_reach_is_not_offered_at_all():
    session = _militia_game(gold_production=1)
    session.game.table.cards_by_id["grounds"].bow()

    assert ActivateAbility("grounds") not in session.legal_actions(P1)


def test_the_grounds_replay_to_the_same_board():
    session = _militia_game()
    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("grounds",)))
    pay(session, P1)
    session.submit(P1, DecisionResponse(("hero",)))

    assert replay(session.log).table == session.game.table


# --- Final Sacrifice ---


def _sacrifice_session(*, yojimbo_bowed: bool = False) -> EngineSession:
    """P2's probe is bowing P1's courtier, with a Yojimbo beside him and Final Sacrifice in hand."""
    game = two_seat_game()
    put_in_play(game, holding("P2-src", owner=P2, printed_id="bow_then_destroy_probe"))
    put_in_play(game, personality("courtier", keywords=("Courtier",)))
    yojimbo = put_in_play(game, personality("yojimbo", keywords=("Yojimbo",)))
    if yojimbo_bowed:
        yojimbo.bow()
    _strategy(game.table, "sacrifice", "final_sacrifice", P1)
    session = EngineSession.start(game.table, P2)
    session.act(P2, ActivateAbility("P2-src"))
    session.submit(P2, DecisionResponse(("courtier",)))
    return session


def test_final_sacrifice_targets_a_yojimbo_and_the_action_goes_for_him_instead():
    session = _sacrifice_session()
    assert session.game.round.kind is RoundKind.INTERRUPT
    assert session.legal_actions(P1) == [Pass(), PlayInterrupt("sacrifice")]

    session.act(P1, PlayInterrupt("sacrifice"))
    target = session.game.pending
    assert isinstance(target, ChooseInterruptTarget)
    assert target.candidates == ("yojimbo",)
    session.submit(P1, DecisionResponse(("yojimbo",)))
    pay(session, P1)

    assert session.game.pending is None
    on_the_table = {card.id for card in session.game.table.battlefield.cards}
    assert "courtier" in on_the_table and not session.game.table.cards_by_id["courtier"].bowed
    assert "yojimbo" not in on_the_table
    assert session.game.action_targets == ("yojimbo",)


def test_final_sacrifice_is_not_offered_when_no_yojimbo_is_a_legal_target():
    # "If legal": the probe targets an unbowed Personality, so a bowed Yojimbo cannot take the
    # courtier's place and the Interrupt is not offered.
    session = _sacrifice_session(yojimbo_bowed=True)

    assert session.game.round.kind is not RoundKind.INTERRUPT
    assert "courtier" not in {card.id for card in session.game.table.battlefield.cards}


def test_final_sacrifice_answers_the_targeting_and_not_what_the_action_then_does():
    game = two_seat_game()
    put_in_play(game, holding("P2-src", owner=P2, printed_id="bow_then_destroy_probe"))
    put_in_play(game, personality("courtier", keywords=("Courtier",)))
    put_in_play(game, personality("yojimbo", keywords=("Yojimbo",)))
    _strategy(game.table, "sacrifice", "final_sacrifice", P1)
    game.action = ActivateAbility("P2-src")
    game.action_targets = ("courtier",)

    resolve_action_effects(game, [Bow("courtier")])

    assert game.round.kind is not RoundKind.INTERRUPT
    assert game.table.cards_by_id["courtier"].bowed


def test_the_final_sacrifice_game_replays_to_the_same_board():
    session = _sacrifice_session()
    session.act(P1, PlayInterrupt("sacrifice"))
    session.submit(P1, DecisionResponse(("yojimbo",)))
    pay(session, P1)

    assert replay(session.log) == session.game
