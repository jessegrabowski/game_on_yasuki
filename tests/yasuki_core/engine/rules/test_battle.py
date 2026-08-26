import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.actions import ActionTiming, DeclareAttack, Pass
from yasuki_core.engine.rules.decisions import assignment, assignment_token
from yasuki_core.engine.rules.policies import EconomicPolicy, GoldRushPolicy
from yasuki_core.engine.rules.state import Phase
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from tests.yasuki_core.engine.builders import end_phase, province_card, two_seat_game


def _session(*, defender_provinces: int = 3) -> EngineSession:
    """A game whose Defender holds ``defender_provinces`` Provinces, so a declaration has somewhere
    to put its battlefields. P1 is active and so is always the Attacker."""
    state = TableState.empty_two_seat()
    for idx in range(defender_provinces):
        province_card(state, f"def-prov{idx}", seat=PlayerId.P2, index=idx)
    province_card(state, "atk-prov0", seat=PlayerId.P1, index=0)
    return EngineSession.start(state, PlayerId.P1)


def _to_battle(session: EngineSession) -> EngineSession:
    """Pass out of the Action phase, leaving the Attack Phase open and undeclared."""
    end_phase(session)
    assert session.game.phase is Phase.BATTLE
    return session


def _province(seat: PlayerId, idx: int) -> ZoneKey:
    return ZoneKey(seat, ZoneRole.PROVINCE, idx)


def test_a_game_starts_with_no_attack():
    assert _session().game.attack is None


def test_the_attack_phase_permits_only_the_declaration():
    session = _to_battle(_session())

    assert session.game.round.timings.active == frozenset({ActionTiming.ATTACK})
    assert session.game.round.timings.others == frozenset()


def test_declare_is_offered_to_the_active_seat_alone():
    session = _to_battle(_session())

    assert DeclareAttack() in session.legal_actions(PlayerId.P1)
    assert session.legal_actions(PlayerId.P2) == []


def test_declare_is_not_offered_outside_the_attack_phase():
    session = _session()

    assert DeclareAttack() not in session.legal_actions(PlayerId.P1)


def test_declare_is_not_offered_twice_in_one_phase():
    session = _to_battle(_session())

    session.act(PlayerId.P1, DeclareAttack())

    assert session.game.attack is not None
    assert session.legal_actions(PlayerId.P1) == [Pass()]


def test_a_second_declaration_is_refused():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())

    with pytest.raises(ValueError, match="not legal"):
        session.act(PlayerId.P1, DeclareAttack())


def test_declaration_creates_one_battlefield_per_defender_province():
    session = _to_battle(_session(defender_provinces=3))

    session.act(PlayerId.P1, DeclareAttack())

    attack = session.game.attack
    assert attack is not None
    assert attack.attacker is PlayerId.P1
    assert attack.defender is PlayerId.P2
    assert [info.province for info in attack.battlefields] == [
        _province(PlayerId.P2, idx) for idx in range(3)
    ]


def test_the_attackers_own_provinces_are_not_battlefields():
    # Both seats hold one Province, so a declaration that read the wrong seat — or both — is
    # visible in the battlefields it created.
    session = _to_battle(_session(defender_provinces=1))

    session.act(PlayerId.P1, DeclareAttack())

    attack = session.game.attack
    assert attack is not None
    assert [info.province for info in attack.battlefields] == [_province(PlayerId.P2, 0)]


def test_battlefields_are_ordered_by_province_index_not_creation_order():
    # A destroyed Province is replaced at the lowest free index, so the zone dict's insertion order
    # stops matching the left-to-right order the CR calls adjacency.
    session = _to_battle(_session(defender_provinces=3))
    game = session.game
    ops.destroy_province(game.table, PlayerId.P2, _province(PlayerId.P2, 1))
    recreated = ops.create_province(game.table, PlayerId.P2)
    assert recreated == _province(PlayerId.P2, 1)  # reused the hole, and so sits last in the dict

    session.act(PlayerId.P1, DeclareAttack())

    assert game.attack is not None
    assert [info.province.idx for info in game.attack.battlefields] == [0, 1, 2]


def test_a_passed_attack_phase_declares_nothing():
    session = _to_battle(_session())

    end_phase(session)

    assert session.game.phase is Phase.DYNASTY
    assert session.game.attack is None


def test_battlefields_cease_to_exist_when_the_phase_ends():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    assert session.game.attack is not None

    end_phase(session)

    assert session.game.phase is Phase.DYNASTY
    assert session.game.attack is None


def test_an_attack_does_not_survive_into_the_next_turn():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())

    while session.game.turn == 1 and not session.game.awaiting_decision:
        end_phase(session)

    assert session.game.turn == 2  # the loop ran out of turn, not out of patience
    assert session.game.attack is None


def test_a_declared_attack_replays_from_the_log():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    declared = session.game.attack

    replayed = session.log.replay()

    assert replayed.attack == declared


@pytest.mark.parametrize(
    "policy", [EconomicPolicy(), GoldRushPolicy()], ids=lambda policy: policy.name
)
def test_the_economic_policies_decline_the_attack(policy):
    # Neither has a model for a battle, and every published simulation number for the two of them
    # assumes they never take the offer.
    session = _to_battle(_session())
    view = session.project(PlayerId.P1)
    actions = session.legal_actions(PlayerId.P1)
    assert DeclareAttack() in actions

    assert policy.choose(view, actions) == Pass()


def test_the_defender_is_the_one_other_seat():
    game = two_seat_game()

    assert battle.defender_of(game, PlayerId.P1) is PlayerId.P2
    assert battle.defender_of(game, PlayerId.P2) is PlayerId.P1


def test_a_seat_with_no_opponent_has_no_defender():
    game = two_seat_game()
    del game.table.seats[PlayerId.P2]

    with pytest.raises(ValueError, match="0 opponents"):
        battle.defender_of(game, PlayerId.P1)


def test_a_token_names_a_card_and_a_battlefield():
    # The literal pins the wire format, so changing the separator fails here rather than silently
    # in a saved game; the round trip pins the pair of functions against each other.
    assert assignment("hero-1@3") == ("hero-1", 3)
    assert assignment(assignment_token("a_card_id", 0)) == ("a_card_id", 0)


@pytest.mark.parametrize(
    "bogus",
    ["hero-1", "@2", "hero-1@", "hero-1@x"],
    ids=["no separator", "no card", "no index", "index is not a number"],
)
def test_a_token_naming_no_battlefield_is_refused(bogus):
    with pytest.raises(ValueError, match="not an assignment token"):
        assignment(bogus)
