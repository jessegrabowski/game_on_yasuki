import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import PutIntoPlay
from yasuki_core.engine.rules.rulebook.joining import JOIN_RESTRICTIONS, register_join_restriction
from yasuki_core.engine.rules.rulebook.recruit import RECRUIT
from yasuki_core.engine.rules.state import GameState
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState

from tests.yasuki_core.engine.builders import (
    end_phase,
    personality,
    province_card,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2
RESTRICTED = "join_restriction_probe"


def _joins_only_p2(game: GameState, seat: PlayerId) -> bool:
    return seat is P2


@pytest.fixture
def joins_only_p2():
    register_join_restriction(RESTRICTED, _joins_only_p2)
    yield
    JOIN_RESTRICTIONS.pop(RESTRICTED)


@pytest.mark.usefixtures("joins_only_p2")
@pytest.mark.parametrize(("owner", "joined"), [(P2, True), (P1, False)])
def test_a_card_is_put_into_play_only_under_a_player_it_joins(owner, joined):
    game = two_seat_game()
    card = register(game.table, personality("stray", printed_id=RESTRICTED, owner=owner))

    resolve_effects(game, [PutIntoPlay(card.id)])

    assert any(held is card for held in game.table.battlefield.cards) is joined


@pytest.mark.usefixtures("joins_only_p2")
def test_a_card_that_will_not_join_a_player_is_not_offered_for_recruit():
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, gold_production=5))
    province_card(state, "stray", printed_id=RESTRICTED, gold_cost=2)
    session = EngineSession.start(state, P1)
    end_phase(session)
    end_phase(session)

    assert ActivateAbility("stray", RECRUIT) not in session.legal_actions(P1)
