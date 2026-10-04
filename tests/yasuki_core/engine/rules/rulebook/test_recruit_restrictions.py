import pytest

from yasuki_core.engine.rules.rulebook.recruit import RECRUIT
from yasuki_core import ruleset
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.idioms import clan_player
from yasuki_core.engine.rules.rulebook.recruit import recruit_card
from yasuki_core.engine.rules.rulebook.recruit_restrictions import (
    RECRUIT_RESTRICTIONS,
    register_recruit_restriction,
)
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.rules.vocabulary.actions import ActivateAbility
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState

from tests.yasuki_core.engine.builders import end_phase, province_card, put_in_play, stronghold

P1 = PlayerId.P1
RESTRICTED = "recruit_restriction_probe"


@pytest.fixture
def crab_only():
    register_recruit_restriction(RESTRICTED, clan_player(ruleset.CRAB))
    yield
    RECRUIT_RESTRICTIONS.pop(RESTRICTED)


def _dynasty_phase(clan: str) -> EngineSession:
    """P1 a ``clan`` player in the Dynasty phase, with a restricted Holding face-up in a Province
    and gold enough to Recruit it."""
    state = TableState.empty_two_seat()
    put_in_play(state, stronghold(P1, clan=clan, gold_production=5))
    province_card(state, "school", printed_id=RESTRICTED, gold_cost=2)
    session = EngineSession.start(state, P1)
    end_phase(session)  # Action -> Battle
    end_phase(session)  # Battle -> Dynasty
    return session


@pytest.mark.usefixtures("crab_only")
@pytest.mark.parametrize(("clan", "offered"), [(ruleset.CRAB, True), (ruleset.DRAGON, False)])
def test_a_restricted_card_is_offered_for_recruit_only_to_the_named_player(clan, offered):
    session = _dynasty_phase(clan)

    assert (ActivateAbility("school", RECRUIT) in session.legal_actions(P1)) is offered


@pytest.mark.usefixtures("crab_only")
def test_an_effect_cannot_recruit_a_restricted_card_for_another_player():
    session = _dynasty_phase(ruleset.DRAGON)

    resolve_effects(
        session.game, recruit_card(session.game, session.game.table.cards_by_id["school"])
    )

    school = session.game.table.cards_by_id["school"]
    assert school not in session.game.table.battlefield.cards
    assert session.game.pending is None
