import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import units_at
from yasuki_core.engine.rules.vocabulary.actions import PlayStrategy
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import combat_segment, personality

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Defeat the Reserves ---


def _reserves_battle(*, highest_chi: int) -> EngineSession:
    """P1's raider against three of P2's Personalities, the first with ``highest_chi`` Chi and the
    others with 1, and Defeat the Reserves in P1's hand."""
    reserves = L5RCard.of(
        ActionPrint,
        id="reserves",
        printed_id="defeat_the_reserves",
        name="Defeat the Reserves",
        side=Side.FATE,
        owner=P1,
        gold_cost=0,
    )
    cards = [
        personality("raider"),
        personality("captain", owner=P2, chi=highest_chi),
        personality("second", owner=P2, chi=1),
        personality("third", owner=P2, chi=1),
    ]
    p2_army = {"captain": 0, "second": 0, "third": 0}
    return combat_segment(cards, {"raider": 0}, p2_army, in_hand=[reserves])


def _p2_units_at_the_battle(session: EngineSession) -> set[str]:
    return {card.id for card in units_at(session.game, 0, P2)}


def test_defeat_the_reserves_has_the_player_move_units_home_until_none_exceed_the_chi():
    session = _reserves_battle(highest_chi=1)

    session.act(P1, PlayStrategy("reserves"))
    session.submit(P1, DecisionResponse(("P2",)))
    assert session.game.pending.seat is P2
    session.submit(P2, DecisionResponse(("third",)))
    session.submit(P2, DecisionResponse(("second",)))

    assert session.game.pending is None
    assert _p2_units_at_the_battle(session) == {"captain"}


@pytest.mark.parametrize("highest_chi", [3, 4])
def test_defeat_the_reserves_moves_nothing_while_the_units_are_within_the_chi(highest_chi):
    session = _reserves_battle(highest_chi=highest_chi)

    session.act(P1, PlayStrategy("reserves"))
    session.submit(P1, DecisionResponse(("P2",)))

    assert _p2_units_at_the_battle(session) == {"captain", "second", "third"}
