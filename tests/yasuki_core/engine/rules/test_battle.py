import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.actions import ActionTiming, DeclareAttack, Pass
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    ChooseBattlefield,
    DecisionResponse,
    assignment,
    assignment_token,
)
from yasuki_core.engine.rules.policies import EconomicPolicy, GoldRushPolicy
from yasuki_core.engine.rules.state import Phase, Segment
from yasuki_core.engine.rules.victory import VictoryRule
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces import keywords
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
    stronghold,
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


def _fight_every_battlefield(session: EngineSession) -> None:
    """Fight out the attack, taking each battlefield in the order the engine offers it.

    Bounded by the battlefield count rather than looping until nothing is pending, so a fight loop
    that failed to advance fails the test instead of hanging it.
    """
    attack = session.game.attack
    assert attack is not None
    for _ in attack.battlefields:
        pending = session.game.pending
        assert isinstance(pending, ChooseBattlefield)
        session.submit(pending.seat, DecisionResponse((pending.candidates[0],)))


def _province(seat: PlayerId, idx: int) -> ZoneKey:
    return ZoneKey(seat, ZoneRole.PROVINCE, idx)


def _hero_ids(seat: PlayerId, count: int) -> list[str]:
    """The ids :func:`_session` gives ``seat``'s Personalities."""
    return [f"{seat.name}-hero{i}" for i in range(count)]


def _request(candidates: tuple[str, ...]) -> AssignUnits:
    return AssignUnits(seat=PlayerId.P1, candidates=candidates, battlefields=2)


def _declared(defender_provinces: int = 2, units: int = 2) -> tuple[EngineSession, list[str]]:
    """A declared attack with ``units`` unbowed Personalities in each seat's home, paused on the
    Attacker's assignment question. Returns the session and the Attacker's Personality ids."""
    session = _to_battle(_session(defender_provinces=defender_provinces, units=units))
    session.act(PlayerId.P1, DeclareAttack())
    return session, _hero_ids(PlayerId.P1, units)


def _one_battlefield(
    attackers: dict[str, int],
    defenders: dict[str, int],
    *,
    province_strength: int = 0,
    defender_provinces: int = 1,
) -> EngineSession:
    """An attack on a single Province, with the named Personalities assigned to it at the Force each
    is given. Paused on the Attacker's choice of where to fight, which has only one answer.

    ``province_strength`` is printed on the Defender's Stronghold, which is where every one of its
    Provinces takes its base from. Only the battlefield at its first Province is fought over.
    """
    state = TableState.empty_two_seat()
    for index in range(defender_provinces):
        province_card(state, f"def-prov{index}", seat=PlayerId.P2, index=index)
    province_card(state, "atk-prov0", seat=PlayerId.P1, index=0)
    put_in_play(state, stronghold(PlayerId.P2, province_strength=province_strength))
    for card_id, force in {**attackers, **defenders}.items():
        owner = PlayerId.P1 if card_id in attackers else PlayerId.P2
        put_in_play(state, personality(card_id, owner=owner, force=force))
    session = _to_battle(EngineSession.start(state, PlayerId.P1))

    session.act(PlayerId.P1, DeclareAttack())
    session.submit(PlayerId.P1, DecisionResponse(tuple(assignment_token(c, 0) for c in attackers)))
    session.submit(PlayerId.P2, DecisionResponse(tuple(assignment_token(c, 0) for c in defenders)))
    return session


def _in_play(session: EngineSession, card_id: str) -> bool:
    return any(card.id == card_id for card in session.game.table.battlefield.cards)


def _fight_one_battle(session: EngineSession) -> None:
    pending = session.game.pending
    assert isinstance(pending, ChooseBattlefield)
    session.submit(pending.seat, DecisionResponse((pending.candidates[0],)))


def _attacker_with_keywords(
    *, personality_keywords: tuple[str, ...] = (), follower_keywords: tuple[str, ...] = ()
) -> EngineSession:
    """A one-battlefield attack the Attacker wins uncontested, its single unit a Personality and one
    Follower carrying the given keywords."""
    state = TableState.empty_two_seat()
    province_card(state, "def-prov0", seat=PlayerId.P2, index=0)
    put_in_play(
        state, personality("hero", owner=PlayerId.P1, force=3, keywords=personality_keywords)
    )
    session = _to_battle(EngineSession.start(state, PlayerId.P1))
    attached(
        session.game,
        attachment(
            "retainer",
            owner=PlayerId.P1,
            attachment_type=AttachmentType.FOLLOWER,
            keywords=follower_keywords,
        ),
        "hero",
    )
    session.act(PlayerId.P1, DeclareAttack())
    session.submit(PlayerId.P1, DecisionResponse((assignment_token("hero", 0),)))
    session.submit(PlayerId.P2, DecisionResponse())
    return session


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
    _fight_every_battlefield(session)

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
    _fight_every_battlefield(session)
    assert session.game.attack is not None

    end_phase(session)

    assert session.game.phase is Phase.DYNASTY
    assert session.game.attack is None


def test_an_attack_does_not_survive_into_the_next_turn():
    session = _to_battle(_session())
    session.act(PlayerId.P1, DeclareAttack())
    _assign_nothing(session)
    _fight_every_battlefield(session)

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


def test_the_defender_answering_opens_the_fight_segment():
    session, _ = _declared()

    session.submit(PlayerId.P1, DecisionResponse())
    session.submit(PlayerId.P2, DecisionResponse())

    assert session.game.attack.segment is Segment.FIGHT
    assert isinstance(session.game.pending, ChooseBattlefield)
    assert session.game.pending.seat is PlayerId.P1  # the Attacker chooses where


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


def test_an_assignment_names_the_window_it_happened_in():
    # Cards ask which maneuvers window a unit came in on, not merely where it ended up. There is one
    # window under these rules, so every entry names it.
    session, heroes = _declared(defender_provinces=1)

    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))

    assert session.game.attack.assigned_in == {heroes[0]: battle.MANEUVERS_WINDOW}


def test_a_unit_that_stayed_home_names_no_window():
    session, heroes = _declared(defender_provinces=1)

    session.submit(PlayerId.P1, DecisionResponse())

    assert heroes[0] not in session.game.attack.assigned_in


def test_both_seats_assign_to_the_same_battlefield():
    session, heroes = _declared(defender_provinces=1)
    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))
    defender = battle.assignable_units(session.game, PlayerId.P2)[0]

    session.submit(PlayerId.P2, DecisionResponse((assignment_token(defender.id, 0),)))

    assert location_of(session.game.table, defender).battlefield == 0
    assert (
        location_of(session.game.table, session.game.table.cards_by_id[heroes[0]]).battlefield == 0
    )


def test_an_attacking_unit_bows_and_comes_home_after_its_battle():
    # After Resolution 0.1: attacking units bow, then return home, both as effects of the
    # resolution. The Defender has nothing there, so nothing destroys the attacker.
    session, heroes = _declared(defender_provinces=1)
    session.submit(PlayerId.P1, DecisionResponse((assignment_token(heroes[0], 0),)))
    session.submit(PlayerId.P2, DecisionResponse())
    card = session.game.table.cards_by_id[heroes[0]]
    assert not location_of(session.game.table, card).is_home

    _fight_every_battlefield(session)

    assert location_of(session.game.table, card).is_home
    assert card.bowed


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


def test_an_armys_force_is_the_sum_of_its_units():
    session = _one_battlefield({"a": 3, "b": 4}, {"d": 5})

    assert battle.army_force(session.game, 0, PlayerId.P1) == 7
    assert battle.army_force(session.game, 0, PlayerId.P2) == 5


def test_a_side_with_no_units_has_zero_force():
    session = _one_battlefield({"a": 3}, {})

    assert battle.army_force(session.game, 0, PlayerId.P2) == 0


def test_a_bowed_personality_contributes_nothing_at_resolution():
    session = _one_battlefield({"a": 3, "b": 4}, {"d": 5})
    session.game.table.cards_by_id["b"].bow()

    assert battle.army_force(session.game, 0, PlayerId.P1) == 3


def test_the_attacker_winning_destroys_the_defending_army():
    session = _one_battlefield({"a": 5}, {"d": 2})

    _fight_one_battle(session)

    assert not _in_play(session, "d")
    assert _in_play(session, "a")


def test_the_defender_winning_destroys_the_attacking_army():
    session = _one_battlefield({"a": 2}, {"d": 5})

    _fight_one_battle(session)

    assert not _in_play(session, "a")
    assert _in_play(session, "d")


def test_a_tie_with_units_on_both_sides_destroys_both_armies():
    session = _one_battlefield({"a": 4}, {"d": 4})

    _fight_one_battle(session)

    assert not _in_play(session, "a")
    assert not _in_play(session, "d")


def test_a_tie_on_zero_force_with_an_empty_side_has_no_outcome():
    # Not the same as a tie that destroys nothing: nobody wins, nobody loses, and no honor moves.
    session = _one_battlefield({}, {"d": 0})
    honor_before = {seat: session.game.table.seats[seat].honor for seat in PlayerId}

    _fight_one_battle(session)

    assert _in_play(session, "d")
    assert {seat: session.game.table.seats[seat].honor for seat in PlayerId} == honor_before


def test_the_province_survives_when_force_only_matches_its_strength():
    # Strictly greater, not equal: attacking 5 against 2 defending and Province Strength 3 is exactly
    # the threshold and leaves the Province standing.
    session = _one_battlefield({"a": 5}, {"d": 2}, province_strength=3)

    _fight_one_battle(session)

    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) in session.game.table.zones


def test_the_province_falls_when_force_clears_its_strength():
    session = _one_battlefield({"a": 6}, {"d": 2}, province_strength=3)

    _fight_one_battle(session)

    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) not in session.game.table.zones


def test_honor_is_twice_the_cards_destroyed_not_the_units():
    # One unit, three cards. Counting units would pay 2 and counting cards pays 6, so the multi-
    # Follower unit is what makes the two readings disagree.
    session = _one_battlefield({"a": 5}, {"d": 2})
    for follower_id in ("f1", "f2"):
        attached(
            session.game,
            attachment(follower_id, owner=PlayerId.P2, attachment_type=AttachmentType.FOLLOWER),
            "d",
        )
    before = session.game.table.seats[PlayerId.P1].honor

    _fight_one_battle(session)

    assert session.game.table.seats[PlayerId.P1].honor - before == 6


def test_a_tie_pays_each_seat_for_the_army_it_destroyed():
    session = _one_battlefield({"a": 4}, {"d": 4})
    seats = session.game.table.seats
    before = {seat: seats[seat].honor for seat in PlayerId}

    _fight_one_battle(session)

    assert seats[PlayerId.P1].honor - before[PlayerId.P1] == 2
    assert seats[PlayerId.P2].honor - before[PlayerId.P2] == 2


def test_a_losing_army_pays_its_destroyer_nothing_extra_for_the_province():
    # Honor counts cards in the enemy army; a destroyed Province is not one of them.
    session = _one_battlefield({"a": 6}, {"d": 2}, province_strength=3)
    before = session.game.table.seats[PlayerId.P1].honor

    _fight_one_battle(session)

    assert session.game.table.seats[PlayerId.P1].honor - before == 2


def test_every_battlefield_is_fought_exactly_once():
    session, _ = _declared(defender_provinces=3, units=0)
    session.submit(PlayerId.P1, DecisionResponse())
    session.submit(PlayerId.P2, DecisionResponse())

    fought_at = []
    for _ in range(3):
        pending = session.game.pending
        assert isinstance(pending, ChooseBattlefield)
        fought_at.append(int(pending.candidates[0]))
        session.submit(pending.seat, DecisionResponse((pending.candidates[0],)))

    assert sorted(fought_at) == [0, 1, 2]
    assert session.game.attack.fought == frozenset({0, 1, 2})
    assert session.game.pending is None


def test_a_battlefield_already_fought_at_is_not_offered_again():
    session, _ = _declared(defender_provinces=3, units=0)
    session.submit(PlayerId.P1, DecisionResponse())
    session.submit(PlayerId.P2, DecisionResponse())
    first = session.game.pending.candidates[0]

    session.submit(PlayerId.P1, DecisionResponse((first,)))

    assert first not in session.game.pending.candidates


def test_the_defender_holds_its_battlefield_until_the_last_battle():
    # After Resolution 0.2: defending units go home only once the Attack Phase's last battle is over.
    state = TableState.empty_two_seat()
    for idx in range(2):
        province_card(state, f"def-prov{idx}", seat=PlayerId.P2, index=idx)
    put_in_play(state, personality("holder", owner=PlayerId.P2, force=1))
    session = _to_battle(EngineSession.start(state, PlayerId.P1))
    session.act(PlayerId.P1, DeclareAttack())
    session.submit(PlayerId.P1, DecisionResponse())
    session.submit(PlayerId.P2, DecisionResponse((assignment_token("holder", 0),)))
    holder = session.game.table.cards_by_id["holder"]

    _fight_one_battle(session)  # the battle at the defended battlefield, but not the last one

    assert location_of(session.game.table, holder).battlefield == 0

    _fight_one_battle(session)  # the last battle of the phase

    assert location_of(session.game.table, holder).is_home
    assert not holder.bowed


def test_a_conqueror_unit_goes_home_without_bowing():
    session = _attacker_with_keywords(personality_keywords=(keywords.CONQUEROR,))
    cards = session.game.table.cards_by_id

    _fight_one_battle(session)

    assert location_of(session.game.table, cards["hero"]).is_home
    assert not cards["hero"].bowed
    # "Cards in a Conqueror Personality's unit" — the Follower is exempt too.
    assert not cards["retainer"].bowed


def test_conqueror_on_a_follower_exempts_nobody():
    # The CR keys the exemption on the Personality, not on the unit. Reading it as a unit keyword
    # would let one Conqueror Follower stand a whole army up.
    session = _attacker_with_keywords(follower_keywords=(keywords.CONQUEROR,))
    cards = session.game.table.cards_by_id

    _fight_one_battle(session)

    assert cards["hero"].bowed
    assert cards["retainer"].bowed


def test_a_unit_without_conqueror_bows_every_card_in_it():
    session = _attacker_with_keywords()
    cards = session.game.table.cards_by_id

    _fight_one_battle(session)

    assert cards["hero"].bowed and cards["retainer"].bowed


def test_an_attack_can_name_an_attacker_other_than_the_active_seat():
    # The Declaration Segment always offers it to the active player, but a card that creates an
    # attack names its own Attacker — a Counterattack has the seat that just defended attacking.
    session = _to_battle(_session(defender_provinces=1))

    battle.declare_attack(session.game, PlayerId.P2)

    attack = session.game.attack
    assert attack.attacker is PlayerId.P2
    assert attack.defender is PlayerId.P1
    assert [info.province.owner for info in attack.battlefields] == [PlayerId.P1]


def test_a_battlefield_with_no_units_at_all_has_no_outcome():
    # The Empty Battlefield: exactly one battle happens at every battlefield, including the ones
    # nobody went to. Nothing is destroyed and no honor moves.
    session = _one_battlefield({}, {})
    seats = session.game.table.seats
    before = {seat: seats[seat].honor for seat in PlayerId}

    _fight_one_battle(session)

    assert session.game.attack.fought == frozenset({0})
    assert {seat: seats[seat].honor for seat in PlayerId} == before
    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) in session.game.table.zones


def test_a_tie_never_destroys_the_province():
    # Only an Attacker who wins can take a Province, and only by clearing its Strength. A tie that
    # wipes both armies leaves the land alone.
    session = _one_battlefield({"a": 4}, {"d": 4})

    _fight_one_battle(session)

    assert not _in_play(session, "a") and not _in_play(session, "d")
    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) in session.game.table.zones


def test_losing_the_last_province_loses_the_game():
    # CR, Military Loss/Victory: a player loses immediately with no Provinces remaining.
    session = _one_battlefield({"a": 6}, {"d": 2}, province_strength=3)
    assert session.game.loser is None

    _fight_one_battle(session)

    assert session.game.loser is PlayerId.P2
    assert session.game.game_over


def test_losing_a_province_that_is_not_the_last_does_not_end_the_game():
    session = _one_battlefield({"a": 6}, {}, defender_provinces=2)

    _fight_one_battle(session)

    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) not in session.game.table.zones
    assert session.game.loser is None


def test_a_seat_not_held_to_the_military_loss_keeps_playing_without_provinces():
    # The per-seat hatch a card like Hidden Catacombs of the Scorpion needs — "You will not lose,
    # or be eliminated, by Dishonor" is the same shape, one seat excused from one rule.
    session = _one_battlefield({"a": 6}, {"d": 2}, province_strength=3)
    # Dropping the one rule rather than all of them: with a second member these stop being the same
    # answer, and the test would quietly start asserting something weaker.
    session.game.active_rules[PlayerId.P2] = frozenset(VictoryRule) - {VictoryRule.MILITARY_LOSS}

    _fight_one_battle(session)

    assert ZoneKey(PlayerId.P2, ZoneRole.PROVINCE, 0) not in session.game.table.zones
    assert session.game.loser is None
