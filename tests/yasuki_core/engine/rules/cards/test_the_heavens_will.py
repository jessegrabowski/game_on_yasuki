from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import DeclareAttack, Pass, PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.vocabulary.segments import BattleSegment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import DeckKey, TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    fate_card,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Discretionary Valor ---


def _valor_battle() -> EngineSession:
    """The Combat Segment of P1's attack, the Defender holding the opportunity. P2 defends with
    kakita, keeps an aide home, and holds Discretionary Valor over a one-card Fate deck."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "def-prov0", seat=P2, index=0)
    put_in_play(state, personality("raider", force=3))
    put_in_play(state, personality("kakita", owner=P2, force=2))
    put_in_play(state, personality("aide", owner=P2))
    state.decks[DeckKey(P2, Side.FATE)].cards = [register(state, fate_card("spare", P2))]
    state.zones[ZoneKey(P2, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="valor",
                name="Discretionary Valor",
                printed_id="discretionary_valor",
                side=Side.FATE,
                owner=P2,
                gold_cost=0,
            ),
        )
    )
    session = EngineSession.start(state, P1)
    end_phase(session)
    session.act(P1, DeclareAttack())
    session.submit(P1, DecisionResponse(("raider@0",)))
    session.submit(P2, DecisionResponse(("kakita@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    while session.game.attack.battle_segment is not BattleSegment.COMBAT:
        session.act(session.game.round.priority, Pass())
    return session


def test_discretionary_valor_sends_an_opposed_personality_home_for_honor_and_a_card():
    session = _valor_battle()

    session.act(P2, PlayStrategy("valor"))
    pay(session, P2)
    assert session.game.pending.candidates == ("kakita",)  # neither the raider nor the aide
    session.submit(P2, DecisionResponse(("kakita",)))

    game = session.game
    assert location_of(game.table, game.table.cards_by_id["kakita"]).is_home
    assert game.table.seats[P2].honor == 1
    assert [card.id for card in game.table.zones[ZoneKey(P2, ZoneRole.HAND)].cards] == ["spare"]
