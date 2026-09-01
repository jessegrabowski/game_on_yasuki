from dataclasses import replace

import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import (
    ActionTiming,
    ActivateAbility,
    BattleDesignator,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.decisions import ChooseBattlefield, DecisionResponse
from yasuki_core.engine.rules import abilities, battle, flow, legality, triggers
from yasuki_core.engine.rules.abilities import _ABILITIES, Ability, CardLocation, itself
from yasuki_core.engine.rules.effects import Bow, GrantPriority
from yasuki_core.engine.rules.state import (
    BATTLE_SEGMENT_TIMINGS,
    BEGINNING_OF_COMBAT,
    BattleSegment,
    Boundary,
    Moment,
    RoundKind,
)
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole

from yasuki_core.engine.rules.events import CardDiscarded
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    end_phase,
    holding,
    personality,
    province_card,
    put_in_play,
    register,
)

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _at_the_battlefield_choice(*, provinces: int = 1) -> EngineSession:
    """A session with the armies assigned, paused on the Attacker's choice of where to fight — the
    step before any battle segment has opened."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    for index in range(provinces):
        province_card(state, f"def-prov{index}", seat=DEFENDER, index=index)
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    put_in_play(state, personality("guard", owner=DEFENDER, force=1))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    assert isinstance(session.game.pending, ChooseBattlefield)
    return session


def _in_a_battle(*, provinces: int = 1) -> EngineSession:
    """A session paused in the first battle's opening segment, with a unit on each side of it."""
    session = _at_the_battlefield_choice(provinces=provinces)
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    return session


def test_a_battle_opens_with_the_engage_segment():
    session = _in_a_battle()

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE
    assert session.game.round.kind is RoundKind.BATTLE_SEGMENT


def test_a_response_step_opens_over_a_battle_segment_and_unwinds_back_to_it():
    """The case the old depth-as-proxy guard got wrong. A battle segment suspends the phase round,
    so a Response taken during the battle is the second thing on the stack, not the first — and
    passing it out has to land back in the segment with its own priority, not in the phase."""
    session = _in_a_battle()
    game = session.game
    put_in_play(
        game.table,
        holding("caravansary", printed_id="caravansary", name="Caravansary", owner=ATTACKER),
    )
    game.action_events[:] = [CardDiscarded("some-fate", Side.FATE, ATTACKER)]

    assert flow.open_response_window(game) is True
    assert game.round.kind is RoundKind.RESPONSE
    assert len(game.round_stack) == 2  # the phase round, then the segment it suspended

    flow.close_response_window(game)

    assert game.round.kind is RoundKind.BATTLE_SEGMENT
    assert game.attack.battle_segment is BattleSegment.ENGAGE


def test_the_defender_acts_first_in_both_segments():
    """Both battle segments start with the Defender rather than the active player, which is the one
    way they differ from a phase's round."""
    session = _in_a_battle()

    assert session.game.round.priority is DEFENDER
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.round.priority is DEFENDER


def test_each_segment_permits_only_its_own_designator():
    session = _in_a_battle()

    for seat in (ATTACKER, DEFENDER):
        assert legality.permits(session.game, seat, ActionTiming.ENGAGE)
        assert not legality.permits(session.game, seat, ActionTiming.BATTLE)
        assert not legality.permits(session.game, seat, ActionTiming.OPEN)

    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())

    for seat in (ATTACKER, DEFENDER):
        assert legality.permits(session.game, seat, ActionTiming.BATTLE)
        assert not legality.permits(session.game, seat, ActionTiming.ENGAGE)


def test_the_combat_segment_follows_the_engage_segment():
    session = _in_a_battle()

    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.attack.battlefields[0].outcome is None  # nothing resolved yet


def test_resolution_follows_the_combat_segment_closing():
    """A battle is two Action Rounds and then resolution, so the second round closing is what
    fights it. Nothing resolves while a segment is still open."""
    session = _in_a_battle(provinces=2)
    for _ in range(4):
        session.act(session.game.round.priority, Pass())
    fought = session.game.attack

    in_play = {card.id for card in session.game.table.battlefield.cards}
    outcome = fought.battlefields[0].outcome

    assert outcome is not None and outcome.winner is ATTACKER
    assert "guard" not in in_play  # the Attacker won and destroyed the defending army


def test_a_segment_round_closes_only_once_both_seats_pass():
    """The same contract a phase's round has, re-asserted because the first actor differs."""
    session = _in_a_battle()

    session.act(DEFENDER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE
    assert session.game.round.priority is ATTACKER


def test_every_battle_of_an_attack_opens_its_own_segments():
    """One battle's segments closing must not carry the next battle past its own."""
    session = _in_a_battle(provinces=2)
    for _ in range(4):
        session.act(session.game.round.priority, Pass())

    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE
    assert session.game.round.priority is DEFENDER


def test_closing_a_segment_when_none_is_open_is_refused():
    """Closing pops the round the segment suspended, so doing it with no segment open would hand
    the phase's round back to whatever is beneath it."""
    session = _in_a_battle()
    session.game.attack.battle_segment = None

    with pytest.raises(ValueError, match="no battle segment is open"):
        battle.close_battle_segment(session.game)


def test_resolving_with_no_battlefield_named_is_refused():
    """Resolution reads the outcome off the battlefield being fought at, so arriving with none
    named is a lost battle rather than a resolved one."""
    session = _in_a_battle()
    session.game.attack.battle_segment = BattleSegment.COMBAT
    session.game.attack.current = None

    with pytest.raises(ValueError, match="no battle is being fought"):
        battle.close_battle_segment(session.game)


def _in_a_battle_one_side(*, present: PlayerId) -> EngineSession:
    """A battle where only ``present`` has a unit at the battlefield: the other side declined to
    assign, so it is in the battle without standing in it."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    put_in_play(state, personality("guard", owner=DEFENDER, force=1))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    defending = ("guard@0",) if present is DEFENDER else ()
    session.submit(DEFENDER, DecisionResponse(defending))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    return session


def test_a_seat_with_no_unit_at_the_battlefield_is_permitted_nothing():
    """CR, Rule of Presence: a player must control one or more units at the current battlefield to
    take an action during a battle."""
    session = _in_a_battle_one_side(present=ATTACKER)

    assert legality.permitted_timings(session.game, DEFENDER) == frozenset()
    assert legality.permits(session.game, ATTACKER, ActionTiming.ENGAGE)


def test_a_segment_still_opens_on_a_defender_with_nothing_to_take():
    """The segment opens whatever the board looks like — a seat with no presence can still be moved
    in, so there is no battlefield at which nothing can happen. It holds the opportunity and can
    only pass, which is the CR's alternative to taking an action rather than an action itself."""
    session = _in_a_battle_one_side(present=ATTACKER)

    assert session.game.round.priority is DEFENDER
    assert Pass() in session.legal_actions(DEFENDER)


def test_both_seats_still_have_to_pass_to_close_a_segment_one_cannot_act_in():
    session = _in_a_battle_one_side(present=ATTACKER)

    session.act(DEFENDER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE

    session.act(ATTACKER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.COMBAT


def test_presence_is_not_asked_outside_a_battle():
    """A seat is permitted its phase's designators whether or not it stands anywhere: presence is a
    question only a battle asks."""
    session = _in_a_battle_one_side(present=DEFENDER)
    session.game.attack.battle_segment = None
    session.game.round = session.game.round_stack[-1]

    assert legality.permitted_timings(session.game, ATTACKER)


_ABILITIES["battle_probe"] = Ability(
    timings=(ActionTiming.ENGAGE,),
    label="test",
    cost=lambda game, source: [],
    targets=lambda game, source: [
        card.id for card in game.table.battlefield.cards if card.id.startswith("mark")
    ],
    effects=lambda game, source, target: [],
)
_ABILITIES["battle_probe_home"] = replace(
    _ABILITIES["battle_probe"], battle=frozenset({BattleDesignator.HOME})
)
_ABILITIES["battle_probe_absent"] = replace(
    _ABILITIES["battle_probe"], battle=frozenset({BattleDesignator.ABSENT})
)


def _probe_in_a_battle(printed_id: str, *, at_home: bool) -> EngineSession:
    """A battle where the Attacker's probe card stands at the battlefield or at home, with a mark
    at each place for it to target."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    put_in_play(state, personality("probe", owner=ATTACKER, printed_id=printed_id, force=1))
    put_in_play(state, personality("mark-front", owner=DEFENDER, force=1))
    put_in_play(state, personality("mark-home", owner=DEFENDER, force=1))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    attacking = ("hero@0",) if at_home else ("hero@0", "probe@0")
    session.submit(ATTACKER, DecisionResponse(attacking))
    session.submit(DEFENDER, DecisionResponse(("mark-front@0",)))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    session.act(DEFENDER, Pass())  # the segment opens on the Defender; the probe is the Attacker's
    return session


def _offered(session: EngineSession) -> set[str]:
    return {
        action.card_id
        for action in session.legal_actions(ATTACKER)
        if isinstance(action, ActivateAbility)
    }


def test_an_ability_is_offered_from_a_card_at_the_battlefield():
    session = _probe_in_a_battle("battle_probe", at_home=False)

    assert "probe" in _offered(session)


def test_an_ability_is_withheld_from_a_card_left_at_home():
    """CR, Rules of Location: an action from a card in a unit needs that unit at the current
    battlefield."""
    session = _probe_in_a_battle("battle_probe", at_home=True)

    assert "probe" not in _offered(session)


def test_the_home_designator_lifts_the_location_rule():
    """ShE, Home: usable even if the card is at home rather than the current battlefield."""
    session = _probe_in_a_battle("battle_probe_home", at_home=True)

    assert "probe" in _offered(session)


def test_the_home_designator_does_not_lift_the_presence_rule():
    """ShE, Home: "It cannot be used without presence unless it also has the Absent designator." The
    two rules are independent, which is what stops this being one flag."""
    session = _probe_in_a_battle("battle_probe_home", at_home=True)
    ops.return_home(session.game.table, session.game.table.cards_by_id["hero"])

    assert "probe" not in _offered(session)


def test_the_absent_designator_does_not_lift_the_location_rule():
    """The independence read the other way: Absent gets a seat with no presence into the battle, and
    leaves a card in a unit stranded at home all the same."""
    session = _probe_in_a_battle("battle_probe_absent", at_home=True)

    assert "probe" not in _offered(session)


_ABILITIES["absent_probe_in_hand"] = Ability(
    timings=(ActionTiming.BATTLE,),
    label="test",
    cost=lambda game, source: [],
    targets=itself,
    effects=lambda game, source, target: [],
    all_targets=True,
    battle=frozenset({BattleDesignator.ABSENT}),
    located_at=(CardLocation.HAND,),
)
_ABILITIES["plain_probe_in_hand"] = replace(_ABILITIES["absent_probe_in_hand"], battle=frozenset())


def _in_hand(session: EngineSession, card_id: str, printed_id: str) -> None:
    """Deal ``card_id`` to the Attacker's hand as a Strategy of ``printed_id``."""
    table = session.game.table
    card = register(
        table,
        L5RCard.of(
            ActionPrint,
            id=card_id,
            name=card_id,
            printed_id=printed_id,
            side=Side.FATE,
            owner=ATTACKER,
        ),
    )
    table.zones[ZoneKey(ATTACKER, ZoneRole.HAND)].add(card)


def _playable(session: EngineSession) -> set[str]:
    return {
        action.card_id
        for action in session.legal_actions(ATTACKER)
        if isinstance(action, PlayStrategy)
    }


def _in_the_combat_segment_with_no_presence(*hand: tuple[str, str]) -> EngineSession:
    """The Combat Segment of a battle the Attacker has no unit standing in, holding the opportunity
    with ``hand`` dealt to it.

    The cards are dealt before the Defender hands the opportunity over, because whether the Attacker
    is asked at all is itself the Absent question: a seat with no presence and nothing Absent to
    play is skipped rather than offered a round it can do nothing in.
    """
    session = _probe_in_a_battle("battle_probe", at_home=True)
    session.act(ATTACKER, Pass())  # out of the Engage Segment and into the Combat Segment
    ops.return_home(session.game.table, session.game.table.cards_by_id["hero"])
    for card_id, printed_id in hand:
        _in_hand(session, card_id, printed_id)
    session.act(DEFENDER, Pass())
    return session


def test_an_absent_card_is_played_without_presence_at_the_battlefield():
    """ShE, Absent: playable without presence at the current battlefield."""
    session = _in_the_combat_segment_with_no_presence(("absent", "absent_probe_in_hand"))

    assert "absent" in _playable(session)


def test_an_absent_card_does_not_carry_the_seats_other_cards_into_the_battle():
    """One Absent card gets the seat asked; it does not lift the rule off everything else in hand.
    The pair is the same ability with and without the designator, so that is all that differs."""
    session = _in_the_combat_segment_with_no_presence(
        ("absent", "absent_probe_in_hand"), ("plain", "plain_probe_in_hand")
    )

    playable = _playable(session)

    assert "absent" in playable
    assert "plain" not in playable


def test_a_target_left_at_home_is_filtered_out_centrally():
    """CR, Rules of Location: a card in a unit may only be targeted at the current battlefield. The
    probe offers both marks and the engine narrows them, so no card handler has to remember to."""
    session = _probe_in_a_battle("battle_probe", at_home=False)
    probe = session.game.table.cards_by_id["probe"]
    ability = _ABILITIES["battle_probe"]

    assert set(ability.targets(session.game, probe)) == {"mark-front", "mark-home"}
    assert abilities.legal_targets(session.game, probe, ability) == ["mark-front"]


_ABILITIES["battle_probe_remote"] = replace(
    _ABILITIES["battle_probe"], battle=frozenset({BattleDesignator.REMOTE})
)


def _probe_at_another_battlefield(printed_id: str) -> EngineSession:
    """Two battlefields, the battle fought at the first, and the Attacker's probe standing at the
    second — at a battlefield, but not this one."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    for index in range(2):
        province_card(state, f"def-prov{index}", seat=DEFENDER, index=index)
    put_in_play(state, personality("hero", owner=ATTACKER, force=3))
    put_in_play(state, personality("probe", owner=ATTACKER, printed_id=printed_id, force=1))
    put_in_play(state, personality("mark-front", owner=DEFENDER, force=1))
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0", "probe@1")))
    session.submit(DEFENDER, DecisionResponse(("mark-front@0",)))
    choice = session.game.pending
    assert isinstance(choice, ChooseBattlefield)
    session.submit(choice.seat, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    return session


def test_the_remote_designator_reaches_from_another_battlefield():
    """ShE, Remote: usable even if the card is at home *or also at another battlefield* — the second
    half is the whole of what makes it wider than Home."""
    session = _probe_at_another_battlefield("battle_probe_remote")

    assert "probe" in _offered(session)


def test_the_home_designator_does_not_reach_from_another_battlefield():
    """ShE, Home: usable "even if the card is at home rather than the current battlefield". A card
    standing at a different battlefield is at neither, and Home does not name it."""
    session = _probe_at_another_battlefield("battle_probe_home")

    assert "probe" not in _offered(session)


def test_the_target_filter_holds_when_the_action_is_actually_taken():
    """The filter has two call sites — what is offered, and what the action is then pointed at. A
    card handler that offered a stranded target would otherwise reach the second unchecked."""
    session = _probe_in_a_battle("battle_probe", at_home=False)

    session.act(ATTACKER, ActivateAbility("probe"))

    asked = session.game.pending
    assert asked is not None
    assert asked.candidates == ("mark-front",)


def _walk_to(session: EngineSession, segment: BattleSegment) -> None:
    """Pass until ``segment`` is the one open. The first battle segment is already open when a
    battle starts, so reaching it is a walk of no steps."""
    for _ in range(4):
        if session.game.attack.battle_segment is segment:
            return
        session.act(session.game.round.priority, Pass())
    raise AssertionError(f"{segment} never opened")


@pytest.mark.parametrize("segment", list(BATTLE_SEGMENT_TIMINGS))
def test_a_delay_to_a_segments_beginning_resolves_as_it_opens(segment):
    """A battle segment's beginning is fired generically as its round opens rather than named at a
    call site, so this is what stands behind its entry in ``FIRED_MOMENTS`` — a moment listed there
    with nothing firing it would hold an effect for the rest of the game."""
    session = _at_the_battlefield_choice()
    session.game.delayed = [(Moment(segment, Boundary.BEGINNING), Bow("guard"))]

    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    _walk_to(session, segment)

    assert session.game.delayed == []
    assert session.game.table.cards_by_id["guard"].bowed


def test_a_delayed_grant_lands_on_the_round_it_was_held_for():
    """The grant is committed after the round exists, so it names the opportunity in the segment it
    was held for rather than in the one it was scheduled from."""
    session = _in_a_battle()
    session.game.delayed = [(BEGINNING_OF_COMBAT, GrantPriority(ATTACKER))]

    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.COMBAT
    assert session.game.round.priority is ATTACKER


def test_granting_the_opportunity_restarts_the_count_of_consecutive_passes():
    """A round closes on consecutive passes, and a seat handed the opportunity has not passed on it
    — so a pass already made before the grant must not be one of the two that close the round."""
    session = _in_a_battle()
    session.act(DEFENDER, Pass())

    triggers.resolve_effects(session.game, [GrantPriority(ATTACKER)])
    session.act(ATTACKER, Pass())

    assert session.game.attack.battle_segment is BattleSegment.ENGAGE
