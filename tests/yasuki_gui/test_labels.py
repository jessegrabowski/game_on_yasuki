import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.state import Phase, Segment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_gui.labels import PHASE_LABELS, turn_context

from tests.yasuki_core.engine.builders import personality, province_card, put_in_play

P1, P2 = PlayerId.P1, PlayerId.P2


def _session():
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=P1, index=0)
    province_card(state, "prov0", seat=P2, index=0)
    put_in_play(state, personality("host", owner=P1, force=3))
    return EngineSession.start(state, P1)


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (Phase.ACTION, "Your Action Phase"),
        (Phase.BATTLE, "Your Attack Phase"),
        (Phase.DYNASTY, "Your Dynasty Phase"),
    ],
)
def test_it_names_the_phase_the_seat_is_standing_in(phase, expected):
    session = _session()
    session.game.phase = phase

    assert turn_context(session.project(P1)) == expected


def test_the_phase_belongs_to_whoever_is_taking_the_turn():
    """Both seats see one turn, so the possessive follows the active player rather than whoever
    happens to hold the opportunity to act inside it."""
    session = _session()

    assert turn_context(session.project(P2)) == "Opponent's Action Phase"


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        (Segment.DECLARATION, "Your Declaration Segment"),
        (Segment.MANEUVERS, "Your Maneuvers Segment"),
        (Segment.FIGHT, "Your Fight Battles"),
    ],
)
def test_a_declared_attack_names_its_segment_rather_than_the_phase(segment, expected):
    """The Attack Phase walks segments and each is a different question, so the more specific CR
    heading is the useful one once there is an attack to have segments. The spellings are the CR's
    own — Fight Battles is not called a Segment there, so it is not called one here."""
    session = _session()
    session.game.phase = Phase.BATTLE
    battle.declare_attack(session.game, P1)
    session.game.attack.segment = segment

    assert turn_context(session.project(P1)) == expected


def test_every_phase_the_engine_has_carries_a_name():
    """A missing entry is a KeyError in the prompt box mid-game rather than a wrong label."""
    assert set(PHASE_LABELS) == set(Phase)
