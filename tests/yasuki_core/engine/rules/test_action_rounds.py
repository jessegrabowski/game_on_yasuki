import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState
from yasuki_core.engine.rules.rulebook.dynasty_discard import DYNASTY_DISCARD
from yasuki_core.engine.rules.vocabulary.actions import (
    ActionTiming,
    ActivateAbility,
    Pass,
)
from yasuki_core.engine.rules.vocabulary.decisions import DecisionResponse
from yasuki_core.engine.rules.turn.structure import Phase
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.rules.abilities.costs import no_cost
from yasuki_core.engine.rules.abilities.model import Ability, itself
from yasuki_core.engine.rules.effects import AdditionalAction, GrantKeyword
from yasuki_core.engine.rules.vocabulary.modifiers import Duration, KeywordGrant
from yasuki_core.engine.rules.legality import is_legal
from tests.yasuki_core.engine.builders import end_phase, holding, province_card, put_in_play
from tests.yasuki_core.engine.rules.conftest import probe_ability


def _session():
    """A game whose active seat holds Millet Farm (an Open ability with a Farm to target) and a
    face-up Province card it can discard in the Dynasty phase. Two real actions, one that pauses for
    a decision and one that resolves inline."""
    state = TableState.empty_two_seat()
    put_in_play(
        state, holding("millet", printed_id="millet_farm", keywords=("Farm",), gold_production=1)
    )
    put_in_play(
        state, holding("farm", printed_id="plain_farm", keywords=("Farm",), gold_production=2)
    )
    province_card(state, "prov", printed_id="plain_holding")
    return EngineSession.start(state, PlayerId.P1)


def _to_dynasty(session):
    end_phase(session)
    end_phase(session)
    return session


def test_a_phase_opens_a_round_the_active_seat_holds():
    session = _session()

    assert session.game.round.priority is PlayerId.P1
    assert session.game.round.passes == 0
    assert session.game.round.timings.active == frozenset({ActionTiming.OPEN, ActionTiming.LIMITED})
    assert session.game.round.timings.others == frozenset({ActionTiming.OPEN})


def test_the_dynasty_phase_opens_a_round_permitting_only_dynasty_actions():
    session = _to_dynasty(_session())

    assert session.game.phase is Phase.DYNASTY
    assert session.game.round.timings.active == frozenset({ActionTiming.DYNASTY})
    assert session.game.round.timings.others == frozenset()


def test_taking_an_action_keeps_the_round_open():
    # The count reads 1 because the Dynasty round permits P2 nothing, so it passes without being
    # asked; what matters is that the round did not close and the phase did not move.
    session = _to_dynasty(_session())

    session.act(PlayerId.P1, ActivateAbility("prov", DYNASTY_DISCARD))

    assert session.game.phase is Phase.DYNASTY
    assert session.game.round.priority is PlayerId.P1
    assert session.game.round.passes == 1


def test_an_action_yields_the_opportunity_only_once_its_decision_is_answered():
    # Millet Farm pauses to pick a target. Handing the opportunity on mid-action would let the round
    # close under an action that has not finished.
    session = _session()

    session.act(PlayerId.P1, ActivateAbility("millet"))
    assert session.game.awaiting_decision
    assert session.game.round.passes == 0

    session.submit(PlayerId.P1, DecisionResponse(("farm",)))

    assert not session.game.awaiting_decision
    assert session.game.phase is Phase.ACTION
    # The action reset the count and handed the opportunity to P2, which the Action round permits
    # Open actions even holding none.
    assert session.game.round.priority is PlayerId.P2
    assert session.game.round.passes == 0


def test_a_seat_the_round_permits_nothing_never_receives_the_opportunity():
    # No player but the active one may take a Dynasty action, so P1's single pass ends the phase.
    # Were P2 asked anyway, the phase would still be Dynasty with priority sitting on P2.
    session = _to_dynasty(_session())

    session.act(PlayerId.P1, Pass())

    assert session.game.turn == 2
    assert session.game.round.priority is PlayerId.P2


def test_a_seat_the_round_could_let_act_is_asked_even_holding_nothing():
    # P2 has no Open action to take, but the Action round permits it Open actions, so the window is
    # real and the phase does not end until P2 declines it. Auto-passing here would be a strategy
    # decision, and those belong to the policy driving the seat.
    session = _session()

    session.act(PlayerId.P1, Pass())

    assert session.game.phase is Phase.ACTION
    assert session.game.round.priority is PlayerId.P2


def test_an_action_then_a_pass_still_closes_the_round():
    # Taking an action resets the count, so the seat that acted must decline again before the round
    # can end. The round must still end rather than staying open behind the reset.
    session = _to_dynasty(_session())

    session.act(PlayerId.P1, ActivateAbility("prov", DYNASTY_DISCARD))
    session.act(PlayerId.P1, Pass())

    assert session.game.turn == 2


def test_a_turn_walks_its_phases_and_hands_off_at_the_end():
    # The whole turn, to catch a round that closes twice or not at all as the turn rolls over.
    session = _session()

    end_phase(session)
    assert session.game.phase is Phase.BATTLE
    end_phase(session)
    assert session.game.phase is Phase.DYNASTY
    end_phase(session)

    assert session.game.turn == 2
    assert session.game.active is PlayerId.P2
    assert session.game.phase is Phase.ACTION
    assert session.game.round.priority is PlayerId.P2
    assert session.game.round.passes == 0


FOLLOW_UP = ActivateAbility("chosen", "probe")


def _open_probe(effects) -> Ability:
    return Ability(
        timings=(ActionTiming.OPEN,),
        cost=no_cost,
        targets=itself,
        effects=effects,
        hits_every_target=True,
        key="probe",
    )


def _granting(game, source, target):
    return [AdditionalAction(PlayerId.P1, frozenset({FOLLOW_UP}))]


def _doing_nothing(game, source, target):
    return []


@pytest.fixture
def follow_up_session():
    """P1's Action Phase, after a Holding granted an additional action limited to the "chosen"
    Holding's ability. An "other" Holding's ability is left out of the limit."""
    state = TableState.empty_two_seat()
    for card_id in ("granter", "chosen", "other"):
        put_in_play(state, holding(card_id, printed_id=f"{card_id}_probe"))
    with (
        probe_ability("granter_probe", _open_probe(_granting)),
        probe_ability("chosen_probe", _open_probe(_doing_nothing)),
        probe_ability("other_probe", _open_probe(_doing_nothing)),
    ):
        session = EngineSession.start(state, PlayerId.P1)
        session.act(PlayerId.P1, ActivateAbility("granter", "probe"))
        yield session


def test_an_additional_action_limited_to_follow_ups_offers_only_them(follow_up_session):
    assert follow_up_session.legal_actions(PlayerId.P1) == [Pass(), FOLLOW_UP]
    assert not is_legal(follow_up_session.game, PlayerId.P1, ActivateAbility("other", "probe"))


def test_the_limit_ends_with_the_additional_action(follow_up_session):
    follow_up_session.act(PlayerId.P1, FOLLOW_UP)

    assert follow_up_session.game.round.follow_ups is None
    assert follow_up_session.game.round.priority is PlayerId.P2


@pytest.mark.parametrize("spend", ["take", "pass"])
def test_what_was_granted_for_the_additional_action_lapses_once_it_is_spent(
    follow_up_session, spend
):
    granted = KeywordGrant("granter", "chosen", "Probe", Duration.FOR_ADDITIONAL_ACTION)
    follow_up_session.game.ongoing.append(granted)

    follow_up_session.act(PlayerId.P1, FOLLOW_UP if spend == "take" else Pass())

    assert granted not in follow_up_session.game.ongoing


NEXT_FOLLOW_UP = ActivateAbility("other", "probe")


def _granting_a_second_follow_up(game, source, target):
    return [
        GrantKeyword(source.id, source.id, "Probe", Duration.FOR_ADDITIONAL_ACTION),
        AdditionalAction(PlayerId.P1, frozenset({NEXT_FOLLOW_UP})),
    ]


def test_a_follow_up_spent_on_another_limited_one_keeps_what_was_granted_for_the_next():
    state = TableState.empty_two_seat()
    for card_id in ("granter", "chosen", "other"):
        put_in_play(state, holding(card_id, printed_id=f"{card_id}_probe"))
    with (
        probe_ability("granter_probe", _open_probe(_granting)),
        probe_ability("chosen_probe", _open_probe(_granting_a_second_follow_up)),
        probe_ability("other_probe", _open_probe(_doing_nothing)),
    ):
        session = EngineSession.start(state, PlayerId.P1)
        session.act(PlayerId.P1, ActivateAbility("granter", "probe"))

        granted = KeywordGrant("chosen", "chosen", "Probe", Duration.FOR_ADDITIONAL_ACTION)

        session.act(PlayerId.P1, FOLLOW_UP)

        assert session.game.round.follow_ups == frozenset({NEXT_FOLLOW_UP})
        assert granted in session.game.ongoing

        session.act(PlayerId.P1, NEXT_FOLLOW_UP)

        assert granted not in session.game.ongoing
