from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.stats.card_values import effective_force
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import combat_segment, personality, register

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Chasing Osano-Wo ---


def _chasing_battle() -> EngineSession:
    """P1's 3F Monk at home, P1's 2F, 4PH samurai at the battlefield against P2's guard, and
    Chasing Osano-Wo in P1's hand."""
    session = combat_segment(
        [
            personality("monk", keywords=(keywords.MONK,), force=3),
            personality("samurai", force=2, personal_honor=4),
            personality("guard", owner=P2),
        ],
        {"samurai": 0},
        {"guard": 0},
    )
    table = session.game.table
    chasing = L5RCard.of(
        FatePrint,
        id="chasing",
        printed_id="chasing_osano_wo",
        name="Chasing Osano-Wo",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.KIHO, keywords.THUNDER),
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, chasing))
    return session


def test_chasing_osano_wo_bows_a_monk_at_home_and_gives_personal_honor_plus_his_force():
    session = _chasing_battle()

    session.act(P1, PlayStrategy("chasing"))
    session.submit(P1, DecisionResponse(("monk",)))
    assert set(session.game.pending.candidates) == {"samurai", "guard"}
    session.submit(P1, DecisionResponse(("samurai",)))

    table = session.game.table
    assert table.cards_by_id["monk"].bowed
    assert effective_force(session.game, table.cards_by_id["samurai"]) == 2 + 3 + 4


def test_chasing_osano_wo_does_not_offer_a_bowed_monk():
    session = _chasing_battle()
    session.game.table.cards_by_id["monk"].bow()

    assert PlayStrategy("chasing") not in session.legal_actions(P1)
