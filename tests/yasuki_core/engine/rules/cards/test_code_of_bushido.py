from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.cards.code_of_bushido import MEDIUM_FOLLOWER
from yasuki_core.engine.rules.vocabulary.actions import Equip, Pass
from yasuki_core.engine.rules.vocabulary.decisions import ChooseCards, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import (
    attachment,
    pay,
    personality,
    put_in_play,
    register,
    stronghold,
    token_template,
)

P1 = PlayerId.P1


# --- Ichiro Yojimbo ---


def _yojimbo_game():
    state = TableState.empty_two_seat()
    token_template(state, MEDIUM_FOLLOWER, name="Medium Follower", card_type="Follower", force=1)
    put_in_play(state, stronghold(P1, gold_production=4))
    put_in_play(state, personality("lord", force=2, chi=3))
    put_in_play(state, personality("cousin", force=2, chi=3))
    _hand_an_attachment(state, attachment("ichiro", printed_id="ichiro_yojimbo", force=2))
    return EngineSession.start(state, P1)


def _hand_an_attachment(state, card):
    state.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(state, card))


def _equip(session, card_id, target_id):
    session.act(P1, Equip(card_id))
    session.submit(P1, DecisionResponse((target_id,)))
    pay(session, P1)


def test_ichiro_yojimbo_brings_a_second_follower():
    session = _yojimbo_game()

    _equip(session, "ichiro", "lord")
    assert isinstance(session.game.pending, ChooseCards)
    session.submit(P1, DecisionResponse(("cousin",)))

    game = session.game
    created = attachments_of(game, game.table.cards_by_id["cousin"])[0]
    assert created.name == "Medium Follower"
    assert created.is_token is True


def test_the_second_follower_need_not_join_the_personality_ichiro_did():
    session = _yojimbo_game()

    _equip(session, "ichiro", "lord")

    assert set(session.game.pending.candidates) == {"lord", "cousin"}


def test_only_ichiros_own_arrival_brings_a_follower():
    """The trigger fires for every copy in play, so it has to know which one arrived."""
    session = _yojimbo_game()
    game = session.game
    put_in_play(game, personality("other", force=2, chi=3))
    plain = attachment("plain", force=1)
    _hand_an_attachment(game.table, plain)
    _equip(session, "ichiro", "lord")
    session.submit(P1, DecisionResponse(("lord",)))
    session.act(PlayerId.P2, Pass())  # the opportunity comes back around to P1

    _equip(session, "plain", "other")

    assert game.pending is None
    assert attachments_of(game, game.table.cards_by_id["other"]) == (plain,)
