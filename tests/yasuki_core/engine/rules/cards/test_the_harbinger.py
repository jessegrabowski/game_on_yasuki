from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    end_turn,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Flashy Technique ---


def _flashy_in_hand(*copies: str) -> EngineSession:
    """P1's Action Phase with ``copies`` of Flashy Technique in hand, a raider to attack with and
    P2's guard to defend with."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=3))
    put_in_play(state, personality("guard", owner=P2, force=3))
    for card_id in copies:
        state.zones[ZoneKey(P1, ZoneRole.HAND)].add(
            register(
                state,
                L5RCard.of(
                    ActionPrint,
                    id=card_id,
                    name="Flashy Technique",
                    printed_id="flashy_technique",
                    side=Side.FATE,
                    owner=P1,
                    gold_cost=0,
                ),
            )
        )
    return EngineSession.start(state, P1)


def _play(session: EngineSession, card_id: str) -> None:
    session.act(P1, PlayStrategy(card_id))
    pay(session, P1)


def test_flashy_technique_penalizes_personalities_only_while_they_attack():
    session = _flashy_in_hand("flashy")
    _play(session, "flashy")
    raider = session.game.table.cards_by_id["raider"]
    guard = session.game.table.cards_by_id["guard"]
    assert effective_force(session.game, raider) == 3

    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))

    assert effective_force(session.game, raider) == 2
    assert effective_force(session.game, guard) == 3


def test_a_second_flashy_technique_waits_for_the_next_turn():
    session = _flashy_in_hand("first", "second")
    _play(session, "first")
    assert PlayStrategy("second") not in session.legal_actions(P1)

    end_turn(session)
    end_turn(session)

    assert PlayStrategy("second") in session.legal_actions(P1)
