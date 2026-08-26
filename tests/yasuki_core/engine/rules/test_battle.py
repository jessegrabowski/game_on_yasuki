import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.actions import ActionTiming, DeclareAttack, Pass
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.policies import EconomicPolicy, GoldRushPolicy
from yasuki_core.engine.rules.state import Phase, Segment
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, location_of

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
    two_seat_game,
)


def _session(*, defender_provinces: int = 3, units: int = 0) -> EngineSession:
    """A game whose Defender holds ``defender_provinces`` Provinces, so a declaration has somewhere
    to put its battlefields, and each seat ``units`` unbowed Personalities at home. P1 is active and
    so is always the Attacker.

    The Personalities go onto the table before the session opens, so the log's start snapshot holds
    them and a replayed assignment names cards the rebuilt game knows.
    """
    state = TableState.empty_two_seat()
    for idx in range(defender_provinces):
        province_card(state, f"def-prov{idx}", seat=PlayerId.P2, index=idx)
    province_card(state, "atk-prov0", seat=PlayerId.P1, index=0)
    for seat in PlayerId:
        for i in range(units):
            put_in_play(state, personality(f"{seat.name}-hero{i}", owner=seat))
    return EngineSession.start(state, PlayerId.P1)


def _to_battle(session: EngineSession) -> EngineSession:
    """Pass out of the Action phase, leaving the Attack Phase open and undeclared."""
    end_phase(session)
    assert session.game.phase is Phase.BATTLE
    return session


def _assign_nothing(session: EngineSession) -> None:
    """Answer both seats' assignment questions with an empty answer, leaving every unit home.

    Bounded by the seat count rather than looping until nothing is pending, so a segment that failed
    to hand on fails the test instead of hanging it.
    """
    for _ in session.game.table.seats:
        pending = session.game.pending
        assert isinstance(pending, AssignUnits)
        session.submit(pending.seat, DecisionResponse())


def _province(seat: PlayerId, idx: int) -> ZoneKey:
    return ZoneKey(seat, ZoneRole.PROVINCE, idx)


def _hero_ids(seat: PlayerId, count: int) -> list[str]:
    """The ids :func:`_session` gives ``seat``'s Personalities."""
    return [f"{seat.name}-hero{i}" for i in range(count)]


def _request(candidates: tuple[str, ...]) -> AssignUnits:
    return AssignUnits(seat=PlayerId.P1, candidates=candidates, battlefields=2)


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
    _assign_nothing(session)

    assert session.game.attack is not None
    assert session.legal_actions(PlayerId.P1) == [Pass()]


def test_a_second_declaration_is_refused():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    _assign_nothing(session)

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
    _assign_nothing(session)
    assert session.game.attack is not None

    end_phase(session)

    assert session.game.phase is Phase.DYNASTY
    assert session.game.attack is None


def test_an_attack_does_not_survive_into_the_next_turn():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    _assign_nothing(session)

    while session.game.turn == 1 and not session.game.awaiting_decision:
        end_phase(session)

    assert session.game.turn == 2  # the loop ran out of turn, not out of patience
    assert session.game.attack is None


def test_a_declared_attack_replays_from_the_log():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    _assign_nothing(session)
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


def test_every_unbowed_personality_at_home_pairs_with_every_battlefield():
    session = _to_battle(_session(defender_provinces=2, units=2))
    heroes = _hero_ids(PlayerId.P1, 2)
    session.act(PlayerId.P1, DeclareAttack())

    candidates = battle.assignment_candidates(session.game, PlayerId.P1)

    assert set(candidates) == {
        assignment_token(hero, battlefield) for hero in heroes for battlefield in range(2)
    }


def test_a_bowed_personality_is_not_assignable():
    session = _to_battle(_session(defender_provinces=1, units=2))
    standing, bowed = _hero_ids(PlayerId.P1, 2)
    session.game.table.cards_by_id[bowed].bow()
    session.act(PlayerId.P1, DeclareAttack())

    assert battle.assignable_units(session.game, PlayerId.P1) == [
        session.game.table.cards_by_id[standing]
    ]


def test_a_personality_already_at_a_battlefield_is_not_assignable():
    # Assigning moves a unit out of home. A unit already at a battlefield has nowhere to be assigned
    # from, and moving between battlefields is a card effect rather than an assignment.
    session = _to_battle(_session(defender_provinces=1, units=2))
    home, away = _hero_ids(PlayerId.P1, 2)
    session.act(PlayerId.P1, DeclareAttack())
    ops.assign(session.game.table, session.game.table.cards_by_id[away], 0)

    assert [card.id for card in battle.assignable_units(session.game, PlayerId.P1)] == [home]


def test_only_the_seats_own_personalities_are_assignable():
    session = _to_battle(_session(defender_provinces=1, units=1))
    session.act(PlayerId.P1, DeclareAttack())

    assert [card.id for card in battle.assignable_units(session.game, PlayerId.P1)] == _hero_ids(
        PlayerId.P1, 1
    )


def test_there_are_no_candidates_without_a_declared_attack():
    session = _to_battle(_session(units=2))

    assert battle.assignment_candidates(session.game, PlayerId.P1) == ()


def test_assigning_nothing_is_a_well_formed_answer():
    # The CR lets a seat keep some or all of its Personalities home.
    assert _request(("hero@0",)).accepts(DecisionResponse())


def test_an_answer_must_draw_on_the_candidates():
    request = _request(("hero@0", "hero@1"))

    assert request.accepts(DecisionResponse(("hero@1",)))
    assert not request.accepts(DecisionResponse(("someone_else@0",)))


def test_one_unit_cannot_be_assigned_to_two_battlefields():
    request = _request(("hero@0", "hero@1"))

    assert not request.accepts(DecisionResponse(("hero@0", "hero@1")))


def test_two_units_may_go_to_the_same_battlefield():
    request = _request(("hero@0", "other@0"))

    assert request.accepts(DecisionResponse(("hero@0", "other@0")))


def _declared(defender_provinces: int = 2, units: int = 2) -> tuple[EngineSession, list[str]]:
    """A declared attack with ``units`` unbowed Personalities in each seat's home, paused on the
    Attacker's assignment question. Returns the session and the Attacker's Personality ids."""
    session = _to_battle(_session(defender_provinces=defender_provinces, units=units))
    session.act(PlayerId.P1, DeclareAttack())
    return session, _hero_ids(PlayerId.P1, units)


def test_declaring_opens_the_maneuvers_segment():
    session, _ = _declared()

    assert session.game.attack.segment is Segment.MANEUVERS


def test_the_attacker_is_asked_to_assign_first():
    session, _ = _declared()

    assert isinstance(session.game.pending, AssignUnits)
    assert session.game.pending.seat is PlayerId.P1


def test_the_defender_is_asked_after_the_attacker():
    session, _ = _declared()

    session.submit(PlayerId.P1, DecisionResponse())

    assert isinstance(session.game.pending, AssignUnits)
    assert session.game.pending.seat is PlayerId.P2


def test_the_segment_ends_once_the_defender_has_answered():
    session, _ = _declared()

    session.submit(PlayerId.P1, DecisionResponse())
    session.submit(PlayerId.P2, DecisionResponse())

    assert session.game.pending is None
    assert session.game.phase is Phase.BATTLE  # the phase is still open; nothing has passed yet


def test_an_assigned_personality_stands_at_its_battlefield():
    session, heroes = _declared(defender_provinces=2)

    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 1),)))

    card = session.game.table.cards_by_id[heroes[0]]
    assert location_of(session.game.table, card).battlefield == 1
    # The one left behind stays home, which is what "may keep some or all of them home" means.
    assert location_of(session.game.table, session.game.table.cards_by_id[heroes[1]]).is_home


def test_assigning_takes_the_whole_unit_along():
    session, heroes = _declared(defender_provinces=1)
    follower = attached(session.game, attachment("banner", owner=PlayerId.P1), heroes[0])

    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))

    assert location_of(session.game.table, follower).battlefield == 0


def test_both_seats_assign_to_the_same_battlefield():
    session, heroes = _declared(defender_provinces=1)
    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))
    defender = battle.assignable_units(session.game, PlayerId.P2)[0]

    session.submit(PlayerId.P2, DecisionResponse((assignment_token(defender.id, 0),)))

    assert location_of(session.game.table, defender).battlefield == 0
    assert (
        location_of(session.game.table, session.game.table.cards_by_id[heroes[0]]).battlefield == 0
    )


def test_assigned_units_come_home_unbowed_when_the_phase_ends():
    # Bowing an attacking army is an effect of battle resolution, and nothing resolves yet.
    session, heroes = _declared(defender_provinces=1)
    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))
    session.submit(PlayerId.P2, DecisionResponse())
    card = session.game.table.cards_by_id[heroes[0]]
    assert not location_of(session.game.table, card).is_home

    end_phase(session)

    assert session.game.phase is Phase.DYNASTY
    assert location_of(session.game.table, card).is_home
    assert not card.bowed


def test_a_full_maneuvers_segment_replays_from_the_log():
    session, heroes = _declared(defender_provinces=2)
    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 1),)))
    session.submit(PlayerId.P2, DecisionResponse())

    replayed = session.log.replay()

    assert replayed.attack == session.game.attack


def test_a_bowed_follower_does_not_block_its_personality():
    # The CR puts the restriction on the Personality, not the unit. Filtering on the unit instead
    # would strand a whole army behind one bowed Follower.
    session = _to_battle(_session(defender_provinces=1, units=1))
    leader = _hero_ids(PlayerId.P1, 1)[0]
    follower = attached(session.game, attachment("banner", owner=PlayerId.P1), leader)
    follower.bow()
    session.act(PlayerId.P1, DeclareAttack())

    assert [card.id for card in battle.assignable_units(session.game, PlayerId.P1)] == [leader]


def test_opening_the_maneuvers_segment_outside_an_attack_is_an_error():
    with pytest.raises(ValueError, match="no attack is declared"):
        battle.open_maneuvers(two_seat_game())


def test_a_seat_with_nothing_to_assign_is_still_asked():
    # An empty candidate list is an answerable question, not a skipped one: the seat has to decline
    # before the segment moves on, and a segment that skipped it would never reach the Defender.
    session = _to_battle(_session(defender_provinces=1, units=0))

    session.act(PlayerId.P1, DeclareAttack())

    pending = session.game.pending
    assert isinstance(pending, AssignUnits)
    assert pending.seat is PlayerId.P1
    assert pending.candidates == ()

    session.submit(PlayerId.P1, DecisionResponse())

    assert isinstance(session.game.pending, AssignUnits)
    assert session.game.pending.seat is PlayerId.P2
