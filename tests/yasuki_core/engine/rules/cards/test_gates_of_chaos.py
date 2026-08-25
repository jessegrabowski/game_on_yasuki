from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import Recruit
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import maximum_gold_production, untaken_self_grant
from yasuki_core.engine.rules.events import ProducingGold
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.rules.triggers import TriggerContext, _TRIGGERS
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    dealt_table,
    end_phase,
    holding,
    province_card,
    put_in_play,
)

P1 = PlayerId.P1
P2 = PlayerId.P2


def _pits_game(*, target_cost=3, went_second=True):
    """P1's Dynasty phase, with Slave Pits (gp 2) in play and a face-up target to recruit.

    Courtesy is live only for the seat that did not go first, so reaching the state the card cares
    about means giving P2 the first turn and passing through it.
    """
    state = dealt_table(fate_deck=8, hand=0)
    put_in_play(state, holding("sp", owner=P1, printed_id="slave_pits", gold_production=2))
    province_card(state, "target", seat=P1, gold_cost=target_cost)
    session = EngineSession.start(state, P2 if went_second else P1)
    for _ in range(6):
        if session.game.active is P1 and session.game.phase is Phase.DYNASTY:
            break
        end_phase(session)
    else:
        raise AssertionError(f"never reached P1's Dynasty phase: {session.game.phase}")
    return session


def _mine_game(*, target_cost=3):
    """P1's Dynasty phase, with Jade Mine (gp 2) in play and a face-up target to recruit."""
    state = dealt_table(fate_deck=8, hand=0)
    put_in_play(state, holding("jm", owner=P1, printed_id="jade_mine", gold_production=2))
    province_card(state, "target", seat=P1, gold_cost=target_cost)
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)
    return session


def _next_turn(session):
    """Pass through to the seat's own next turn, so its straighten has run."""
    turn = session.game.turn
    for _ in range(8):
        if session.game.turn == turn + 2:
            return
        end_phase(session)
    raise AssertionError("never reached the next turn")


def test_jade_mine_offers_its_grant_on_the_production_window():
    session = _mine_game()
    session.act(P1, Recruit("target"))

    session.submit(P1, DecisionResponse(("jm",)))

    assert session.game.pending.question == (
        "Give Jade Mine +1GP (this turn)? It will not straighten until after your next Action Phase."
    )


def test_a_granted_jade_mine_does_not_straighten_next_turn():
    session = _mine_game()
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("jm",)))
    session.submit(P1, DecisionResponse(("jm",)))  # yes: 3 gold covers the cost

    assert session.game.table.cards_by_id["target"] in session.game.table.battlefield.cards
    assert session.game.table.cards_by_id["jm"].bowed

    _next_turn(session)
    assert session.game.table.cards_by_id["jm"].bowed  # the delay it was granted for

    _next_turn(session)
    assert not session.game.table.cards_by_id["jm"].bowed  # and only one straighten is skipped


def test_the_jade_mine_grant_replays_to_the_same_state():
    """The delay is state the tape has to reproduce, not a fact about the board it can read back."""
    session = _mine_game()
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("jm",)))
    session.submit(P1, DecisionResponse(("jm",)))

    assert session.game.straighten_delayed.keys() == {"jm"}
    assert replay(session.log) == session.game


def test_a_declined_jade_mine_straightens_as_usual():
    session = _mine_game(target_cost=2)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("jm",)))
    session.submit(P1, DecisionResponse(()))  # no

    assert session.game.table.cards_by_id["jm"].bowed

    _next_turn(session)
    assert not session.game.table.cards_by_id["jm"].bowed


def test_a_producer_asked_once_a_turn_is_not_asked_again():
    """The window's own once-per-turn guard, which needs a card that survives its own price to be
    reachable at all — Outlying Farms is destroyed for taking its grant and never gets here."""
    session = _mine_game(target_cost=2)
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("jm",)))
    session.submit(P1, DecisionResponse(("jm",)))  # yes, claiming the turn's use
    mine = session.game.table.cards_by_id["jm"]
    mine.unbow()

    assert untaken_self_grant(session.game, mine) == 0
    assert _window_effects(session.game, mine) == []


def _window_effects(game, producer):
    """What the producer's own window trigger offers, asked directly: the card is only asked once a
    turn and nothing on the board can make it produce twice in one."""
    event = ProducingGold(producer.id, producer.owner)
    return [
        effect
        for trigger in _TRIGGERS.get(ProducingGold, {}).get(producer.printed_id, [])
        for effect in trigger(TriggerContext(game, producer, event))
    ]


def test_slave_pits_offers_its_grant_on_the_production_window():
    session = _pits_game()
    session.act(P1, Recruit("target"))

    session.submit(P1, DecisionResponse(("sp",)))

    assert session.game.pending.question == "Give Slave Pits +1GP (this turn) and lose 2 Honor?"


def test_taking_the_slave_pits_grant_loses_two_honor():
    session = _pits_game()
    before = session.game.table.seats[P1].honor
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("sp",)))

    session.submit(P1, DecisionResponse(("sp",)))  # yes

    assert session.game.table.seats[P1].honor == before - 2
    assert session.game.table.cards_by_id["target"] in session.game.table.battlefield.cards
    assert session.game.gold[P1] == 0  # 3 produced, 3 spent


def test_declining_the_slave_pits_grant_keeps_the_honor():
    session = _pits_game(target_cost=2)
    before = session.game.table.seats[P1].honor
    session.act(P1, Recruit("target"))
    session.submit(P1, DecisionResponse(("sp",)))

    session.submit(P1, DecisionResponse(()))  # no

    assert session.game.table.seats[P1].honor == before
    assert session.game.table.cards_by_id["sp"] in session.game.table.battlefield.cards


def test_slave_pits_does_not_trigger_for_the_first_player():
    """Courtesy traits do not take effect if you went first, so the window opens and passes over."""
    session = _pits_game(target_cost=2, went_second=False)
    session.act(P1, Recruit("target"))

    session.submit(P1, DecisionResponse(("sp",)))

    assert session.game.pending is None  # no question was raised
    assert session.game.table.cards_by_id["target"] in session.game.table.battlefield.cards


def test_the_first_player_is_not_offered_a_recruit_only_courtesy_could_pay_for():
    """Affordability has to read the same gate the trigger does. Counting the grant for a seat the
    card refuses would offer a purchase whose window then declines to help pay for it."""
    going_first = _pits_game(target_cost=3, went_second=False)
    going_second = _pits_game(target_cost=3, went_second=True)

    pits = going_first.game.table.cards_by_id["sp"]
    assert maximum_gold_production(going_first.game, pits) == 2
    assert Recruit("target") not in going_first.legal_actions(P1)

    pits = going_second.game.table.cards_by_id["sp"]
    assert maximum_gold_production(going_second.game, pits) == 3
    assert Recruit("target") in going_second.legal_actions(P1)
