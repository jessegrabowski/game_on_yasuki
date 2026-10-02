from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary import keywords
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import FatePrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    personality,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Palm Strike ---


def _palm_strike_battle(*, armed_monk: bool = False) -> EngineSession:
    """P1's Monk against P2's guard and armed guard at the battlefield, P2's sentry at home, and
    Palm Strike in P1's hand."""
    session = combat_segment(
        [
            personality("monk", keywords=(keywords.MONK,)),
            personality("guard", owner=P2),
            personality("armed", owner=P2),
            personality("sentry", owner=P2),
        ],
        {"monk": 0},
        {"guard": 0, "armed": 0},
    )
    table = session.game.table
    attached(table, attachment("blade", owner=P2, keywords=(keywords.WEAPON,)), "armed")
    if armed_monk:
        attached(table, attachment("sword", keywords=(keywords.WEAPON,)), "monk")
    strike = L5RCard.of(
        FatePrint,
        id="strike",
        printed_id="palm_strike",
        name="Palm Strike",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
        keywords=(keywords.KIHO,),
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, strike))
    return session


def test_palm_strike_bows_an_unarmed_enemy_at_the_battlefield():
    session = _palm_strike_battle()

    session.act(P1, PlayStrategy("strike"))
    session.submit(P1, DecisionResponse(("monk",)))
    assert session.game.pending.candidates == ("guard",)
    session.submit(P1, DecisionResponse(("guard",)))

    assert session.game.table.cards_by_id["guard"].bowed
    assert not session.game.table.cards_by_id["monk"].bowed


def test_palm_strike_needs_an_unarmed_monk():
    session = _palm_strike_battle(armed_monk=True)

    assert PlayStrategy("strike") not in session.legal_actions(P1)
