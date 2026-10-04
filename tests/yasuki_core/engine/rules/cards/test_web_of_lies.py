from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.replay.game_log import replay
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.rules.vocabulary.decisions import (
    ChooseCards,
    DecisionResponse,
    focus_token,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import focus_card, personality, put_in_play, register
from tests.yasuki_core.engine.rules.conftest import probe_ability
from tests.yasuki_core.engine.rules.duel.conftest import CHALLENGE_ABILITY, CHALLENGE_PROBE

P1, P2 = PlayerId.P1, PlayerId.P2


def _duel_with_weigh_the_cost(*, p1_spare: int = 1) -> TableState:
    """P1's challenger against P2's rival, with Weigh the Cost and ``p1_spare`` other focusable
    cards in P1's hand.

    P2 holds one more card than P1 needs focuses, because the duelists alternate and a seat with
    nothing left to focus strikes, which ends the focusing for both.
    """
    state = TableState.empty_two_seat()
    put_in_play(state, personality("challenger", owner=P1, chi=3, printed_id=CHALLENGE_PROBE))
    put_in_play(state, personality("rival", owner=P2, chi=3))
    held = [focus_card("weigh", P1, 3, printed_id="weigh_the_cost")]
    held += [focus_card(f"P1-spare{index}", P1, 1) for index in range(p1_spare)]
    held += [focus_card(f"P2-plain{index}", P2, 1) for index in range(p1_spare + 1)]
    for card in held:
        state.zones[ZoneKey(card.owner, ZoneRole.HAND)].add(register(state, card))
    return state


def test_weigh_the_cost_adds_a_point_to_itself_and_to_the_card_you_pick():
    # Printed Focus Values are 3 on Weigh the Cost and 1 on the spare, so the seat totals its Chi
    # of 3 plus 4 plus 2 once both points land.
    state = _duel_with_weigh_the_cost()
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain0"),)))
        session.submit(P1, DecisionResponse((focus_token("weigh"),)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain1"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-spare0"),)))

        pending = session.game.pending
        assert isinstance(pending, ChooseCards)
        assert pending.candidates == ("P1-spare0",)
        session.submit(P1, DecisionResponse(("P1-spare0",)))

        assert session.game.duel.outcome.totals == {P1: 3 + 4 + 2, P2: 3 + 1 + 1}


def test_weigh_the_cost_asks_nothing_when_it_is_the_only_card_you_focused():
    # "One other of your focused cards" has nothing to name, and a choice of one from none would
    # pend with no answer that satisfies it. The card's own point still applies.
    state = _duel_with_weigh_the_cost(p1_spare=0)
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain0"),)))
        session.submit(P1, DecisionResponse((focus_token("weigh"),)))

        assert session.game.pending is None
        assert session.game.duel.outcome.totals == {P1: 3 + 4, P2: 3 + 1}


def test_weigh_the_cost_cannot_add_its_point_to_the_opponents_focused_card():
    # "Of your focused cards": the other seat's focusing area is not a candidate.
    state = _duel_with_weigh_the_cost()
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain0"),)))
        session.submit(P1, DecisionResponse((focus_token("weigh"),)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain1"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-spare0"),)))

        assert set(session.game.pending.candidates) == {"P1-spare0"}


def test_weigh_the_cost_replays_to_the_same_board():
    state = _duel_with_weigh_the_cost()
    with probe_ability(CHALLENGE_PROBE, CHALLENGE_ABILITY):
        session = EngineSession.start(state, P1)
        session.act(P1, ActivateAbility("challenger"))
        session.submit(P1, DecisionResponse(("rival",)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain0"),)))
        session.submit(P1, DecisionResponse((focus_token("weigh"),)))
        session.submit(P2, DecisionResponse((focus_token("P2-plain1"),)))
        session.submit(P1, DecisionResponse((focus_token("P1-spare0"),)))
        session.submit(P1, DecisionResponse(("P1-spare0",)))

        assert replay(session.log).table == session.game.table
