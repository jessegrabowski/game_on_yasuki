import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint, FatePrint, RingPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    combat_segment,
    personality,
    register,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Aligned with the Elements ---


def _ring() -> L5RCard:
    return L5RCard.of(
        RingPrint, id="ring", printed_id="ring", name="Ring", side=Side.FATE, owner=P1
    )


def _way_of_the_dragon() -> L5RCard:
    return L5RCard.of(
        ActionPrint,
        id="ring",
        printed_id="way_of_the_dragon_experienced",
        name="Way of the Dragon",
        side=Side.FATE,
        owner=P1,
    )


def _aligned_battle(ring: L5RCard | None = None) -> EngineSession:
    """``ring`` in P1's play, P1's samurai against P2's bare guard and armed guard at the
    battlefield, and Aligned with the Elements in P1's hand."""
    session = combat_segment(
        [
            _ring() if ring is None else ring,
            personality("samurai"),
            personality("guard", owner=P2),
            personality("armed", owner=P2),
        ],
        {"samurai": 0},
        {"guard": 0, "armed": 0},
    )
    table = session.game.table
    attached(table, attachment("blade", owner=P2), "armed")
    aligned = L5RCard.of(
        FatePrint,
        id="aligned",
        printed_id="aligned_with_the_elements",
        name="Aligned with the Elements",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    table.zones[ZoneKey(P1, ZoneRole.HAND)].add(register(table, aligned))
    return session


@pytest.mark.parametrize("make_ring", [_ring, _way_of_the_dragon])
def test_aligned_with_the_elements_bows_your_ring_to_bow_an_enemy_card_without_attachments(
    make_ring,
):
    session = _aligned_battle(make_ring())

    session.act(P1, PlayStrategy("aligned", "bow"))
    session.submit(P1, DecisionResponse(("ring",)))
    assert "armed" not in session.game.pending.candidates
    session.submit(P1, DecisionResponse(("guard",)))

    table = session.game.table
    assert table.cards_by_id["ring"].bowed
    assert table.cards_by_id["guard"].bowed


def test_aligned_with_the_elements_straightens_your_bowed_ring_and_an_attachment():
    session = _aligned_battle()
    table = session.game.table
    table.cards_by_id["ring"].bow()
    table.cards_by_id["blade"].bow()

    session.act(P1, PlayStrategy("aligned", "straighten"))
    session.submit(P1, DecisionResponse(("ring",)))
    session.submit(P1, DecisionResponse(("blade",)))

    assert not table.cards_by_id["ring"].bowed
    assert not table.cards_by_id["blade"].bowed
