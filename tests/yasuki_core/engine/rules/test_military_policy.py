from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules import battle
from yasuki_core.engine.rules.actions import DeclareAttack
from yasuki_core.engine.rules.decisions import (
    AssignUnits,
    ChooseBattlefield,
    assignment,
    assignment_token,
    ChoosePayment,
    DecisionResponse,
)
from yasuki_core.engine.rules.policies import GoldRushPolicy, MilitaryPolicy, POLICIES
from yasuki_core.engine.rules.projection import project
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import location_of, TableState
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
    stronghold,
)

DEFENDER = PlayerId.P2
ATTACKER = PlayerId.P1


def _attacked(*, defenders: dict[str, int], attackers: dict[str, int], provinces: int = 2):
    """A game whose Defender holds ``provinces`` Provinces at Strength 0, with the named units in
    play for each seat. The attack itself is declared by :func:`_defend`."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    for index in range(provinces):
        province_card(state, f"prov{index}", seat=DEFENDER, index=index)
    for card_id, force in defenders.items():
        put_in_play(state, personality(card_id, owner=DEFENDER, force=force))
    for card_id, force in attackers.items():
        put_in_play(state, personality(card_id, owner=ATTACKER, force=force))

    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    return session


def _defend(session, sent: dict[str, int]) -> tuple[str, ...]:
    """Send the Attacker's units where ``sent`` says, then ask the policy to defend."""
    game = session.game
    battle.declare_attack(game, ATTACKER)
    for card_id, index in sent.items():
        ops.assign(game.table, game.table.cards_by_id[card_id], index)
    request = AssignUnits(
        seat=DEFENDER,
        candidates=battle.assignment_candidates(game, DEFENDER),
        battlefields=len(game.attack.battlefields),
    )
    answer = MilitaryPolicy().decide(request, project(game, DEFENDER))
    assert request.accepts(answer), "the policy answered with something the engine would refuse"
    return answer.choices


def _sent_to(choices: tuple[str, ...]) -> dict[int, set[str]]:
    """The answer read back as battlefield index to the units sent there."""
    places: dict[int, set[str]] = {}
    for token in choices:
        card_id, index = assignment(token)
        places.setdefault(index, set()).add(card_id)
    return places


def test_the_policy_is_registered_and_takes_no_arguments():
    """`make_policy` calls the class with no arguments and `--policy` reads the registry, so a
    policy that needs constructing by hand cannot be swept."""
    assert POLICIES["military"] is MilitaryPolicy
    assert MilitaryPolicy().name == "military"


class TestDefending:
    def test_it_defends_a_province_it_can_save(self):
        session = _attacked(defenders={"guard": 4}, attackers={"raider": 3})

        assert _sent_to(_defend(session, {"raider": 0})) == {0: {"guard"}}

    def test_it_sends_nothing_where_nothing_attacks(self):
        """A Province nobody came to survives on its own, and a unit sent there is a unit that
        cannot save one that needs it."""
        session = _attacked(defenders={"guard": 4}, attackers={"raider": 3})

        assert _sent_to(_defend(session, {"raider": 1})) == {1: {"guard"}}

    def test_it_defends_what_it_cannot_win_but_can_hold(self):
        """Resolution destroys a Province only when the attack exceeds the defense plus the
        Province's Strength, so a defense that loses the battle can still hold the ground. A seat
        that only contested what it could beat would concede most of the board."""
        session = _attacked(defenders={"guard": 3}, attackers={"raider": 3})

        assert _sent_to(_defend(session, {"raider": 0})) == {0: {"guard"}}

    def test_it_leaves_a_province_it_cannot_hold(self):
        """Units spent on a Province that falls anyway are units it does not have next turn."""
        session = _attacked(defenders={"guard": 1}, attackers={"raider": 9})

        assert _defend(session, {"raider": 0}) == ()

    def test_it_spends_the_fewest_units_that_hold_a_province(self):
        """Three small units where one large one would do leaves two fewer for the next Province."""
        session = _attacked(
            defenders={"big": 5, "small-a": 1, "small-b": 1}, attackers={"raider": 4}
        )

        assert _sent_to(_defend(session, {"raider": 0})) == {0: {"big"}}

    def test_it_saves_as_many_provinces_as_it_can_afford(self):
        """Cheapest first, so a seat short of units saves two Provinces rather than one. Taking the
        battlefields in board order spends everything on the expensive one and saves one.

        Three battlefields, because with two the two orders happen to save the same number and the
        difference does not show.
        """
        session = _attacked(
            defenders={"guard-a": 2, "guard-b": 2},
            attackers={"host": 4, "scout-a": 2, "scout-b": 2},
            provinces=3,
        )

        places = _sent_to(_defend(session, {"host": 0, "scout-a": 1, "scout-b": 2}))

        assert set(places) == {1, 2}  # the expensive Province at 0 is left to fall

    def test_it_never_sends_the_same_unit_twice(self):
        """Two battlefields both need it and a unit stands at one, so an answer naming it twice is
        refused outright rather than being a greedier defense."""
        session = _attacked(defenders={"guard": 4}, attackers={"a": 3, "b": 3})

        places = _sent_to(_defend(session, {"a": 0, "b": 1}))

        assert sum(len(units) for units in places.values()) == 1

    def test_it_counts_a_follower_toward_what_a_unit_can_hold(self):
        """The unit's Force, not the Personality's — a defense weighed on the printed number sends
        two units where one would have held, or none where one would."""
        session = _attacked(defenders={"guard": 2}, attackers={"raider": 5}, provinces=1)
        attached(
            session.game,
            attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=3, owner=DEFENDER),
            "guard",
        )

        assert _sent_to(_defend(session, {"raider": 0})) == {0: {"guard"}}

    def test_it_never_names_a_bowed_defender(self):
        """`assignable_units` leaves bowed Personalities out of the candidates, so the policy must
        take the offered list as the whole of what it may send rather than reading the board."""
        session = _attacked(defenders={"bowed": 9, "ready": 1}, attackers={"raider": 1})
        session.game.table.cards_by_id["bowed"].bow()

        assert _sent_to(_defend(session, {"raider": 0})) == {0: {"ready"}}

    def test_a_province_with_strength_absorbs_part_of_the_attack(self):
        """Strength counts toward holding the Province, so a Province strong enough needs no
        defenders at all."""
        state = TableState.empty_two_seat()
        put_in_play(state, stronghold(DEFENDER, province_strength=5))
        province_card(state, "atk-prov0", seat=ATTACKER, index=0)
        province_card(state, "prov0", seat=DEFENDER, index=0)
        put_in_play(state, personality("guard", owner=DEFENDER, force=4))
        put_in_play(state, personality("raider", owner=ATTACKER, force=3))
        session = EngineSession.start(state, ATTACKER)
        end_phase(session)

        assert _defend(session, {"raider": 0}) == ()


def _attack_answer(session, seat=ATTACKER) -> tuple[str, ...]:
    """Declare, then ask the policy where the Attacker's units go."""
    game = session.game
    battle.declare_attack(game, seat)
    request = AssignUnits(
        seat=seat,
        candidates=battle.assignment_candidates(game, seat),
        battlefields=len(game.attack.battlefields),
    )
    answer = MilitaryPolicy().decide(request, project(game, seat))
    assert request.accepts(answer), "the policy answered with something the engine would refuse"
    return answer.choices


class TestDeclaring:
    def test_it_attacks_when_it_holds_more_force(self):
        session = _attacked(defenders={"guard": 1}, attackers={"raider": 5})
        view = project(session.game, ATTACKER)

        chosen = MilitaryPolicy().choose(view, session.legal_actions(ATTACKER))

        assert isinstance(chosen, DeclareAttack)

    def test_it_passes_when_it_is_outmatched(self):
        session = _attacked(defenders={"guard": 9}, attackers={"raider": 1})
        view = project(session.game, ATTACKER)

        chosen = MilitaryPolicy().choose(view, session.legal_actions(ATTACKER))

        assert not isinstance(chosen, DeclareAttack)

    def test_it_counts_only_what_it_could_send(self):
        """A bowed Personality may not be assigned, so counting his unit would have the seat declare
        an attack it cannot make.

        He carries an unbowed Follower, which is what makes the case visible: a bowed Personality
        contributes nothing on his own, but the CR totals an army over unbowed Personalities *and*
        Followers, so his Follower's Force is still in his unit's total.
        """
        session = _attacked(defenders={"guard": 3}, attackers={"bowed": 1, "ready": 1})
        attached(
            session.game,
            attachment("banner", attachment_type=AttachmentType.FOLLOWER, force=9, owner=ATTACKER),
            "bowed",
        )
        session.game.table.cards_by_id["bowed"].bow()
        view = project(session.game, ATTACKER)
        assert view.unit_force["bowed"] == 9, "the Follower still counts toward the unit"

        chosen = MilitaryPolicy().choose(view, session.legal_actions(ATTACKER))

        assert not isinstance(chosen, DeclareAttack)

    def test_it_does_not_attack_on_even_force(self):
        """Even armies take nothing: a Province falls only to a Force that exceeds the defense plus
        its Strength, so an attack that merely matches spends an army for no ground."""
        session = _attacked(defenders={"guard": 4}, attackers={"raider": 4})
        view = project(session.game, ATTACKER)

        chosen = MilitaryPolicy().choose(view, session.legal_actions(ATTACKER))

        assert not isinstance(chosen, DeclareAttack)

    def test_it_does_not_declare_a_second_attack(self):
        """`legality` withholds the action once an attack stands, so the policy must take what it is
        offered rather than what it would prefer."""
        session = _attacked(defenders={"guard": 1}, attackers={"raider": 5})
        battle.declare_attack(session.game, ATTACKER)
        view = project(session.game, ATTACKER)
        actions = session.legal_actions(ATTACKER)
        assert not any(isinstance(action, DeclareAttack) for action in actions)

        assert not isinstance(MilitaryPolicy().choose(view, actions), DeclareAttack)


class TestAttacking:
    def test_it_takes_a_province_it_can_take_whatever_the_defense_does(self):
        """The Defender assigns after this answer, so a Province is only worth committing to when
        the attack beats its Strength plus everything the Defender could still bring."""
        session = _attacked(defenders={"guard": 2}, attackers={"host": 5}, provinces=1)

        assert _sent_to(_attack_answer(session)) == {0: {"host"}}

    def test_it_leaves_a_province_the_defense_could_hold(self):
        """Exactly enough to beat the defense is not enough — a tie leaves the Province standing and
        destroys both armies."""
        session = _attacked(defenders={"guard": 5}, attackers={"host": 5}, provinces=1)

        assert _attack_answer(session) == ()

    def test_it_counts_province_strength_against_it(self):
        state = TableState.empty_two_seat()
        put_in_play(state, stronghold(DEFENDER, province_strength=4))
        province_card(state, "atk-prov0", seat=ATTACKER, index=0)
        province_card(state, "prov0", seat=DEFENDER, index=0)
        put_in_play(state, personality("guard", owner=DEFENDER, force=1))
        put_in_play(state, personality("host", owner=ATTACKER, force=5))
        session = EngineSession.start(state, ATTACKER)
        end_phase(session)

        assert _attack_answer(session) == ()

    def test_it_spreads_across_the_provinces_it_can_take(self):
        """Two Provinces it can each take, and force for both — a rule that stopped at the first
        would leave the second standing for no reason."""
        session = _attacked(
            defenders={"guard": 1}, attackers={"host-a": 3, "host-b": 3}, provinces=2
        )

        places = _sent_to(_attack_answer(session))

        # Which host goes where is a tie-break, not the behavior under test.
        assert set(places) == {0, 1}
        assert all(len(units) == 1 for units in places.values())

    def test_it_never_sends_the_same_unit_to_two_provinces(self):
        session = _attacked(defenders={"guard": 1}, attackers={"host": 9}, provinces=2)

        places = _sent_to(_attack_answer(session))

        assert sum(len(units) for units in places.values()) == 1


class TestFightOrder:
    def test_it_fights_the_battle_it_leads_by_the_most(self):
        session = _attacked(
            defenders={"guard": 3}, attackers={"host-a": 9, "host-b": 4}, provinces=2
        )
        game = session.game
        battle.declare_attack(game, ATTACKER)
        ops.assign(game.table, game.table.cards_by_id["host-a"], 1)
        ops.assign(game.table, game.table.cards_by_id["host-b"], 0)
        request = ChooseBattlefield(seat=ATTACKER, candidates=("0", "1"))

        answer = MilitaryPolicy().decide(request, project(game, ATTACKER))

        assert request.accepts(answer)
        assert answer.choices == ("1",)  # the battlefield it leads 9-0 rather than 4-0


class TestDelegation:
    def test_it_leaves_the_attacker_s_assignment_alone(self):
        """The Attacker answers the same request class. Sending its units where the defense rule
        points them would be nonsense, and the fallback declines instead."""
        session = _attacked(defenders={"guard": 4}, attackers={"raider": 3})
        game = session.game
        battle.declare_attack(game, ATTACKER)
        request = AssignUnits(
            seat=ATTACKER,
            candidates=battle.assignment_candidates(game, ATTACKER),
            battlefields=len(game.attack.battlefields),
        )

        answer = MilitaryPolicy().decide(request, project(game, ATTACKER))

        assert answer.choices == ()

    def test_it_answers_everything_else_the_way_the_gold_rush_does(self):
        """Only the defending assignment is its own. Answering a payment differently — or not at
        all — would strand a driven game on the first thing it buys."""
        request = ChoosePayment(
            seat=DEFENDER,
            candidates=("purse",),
            amount=4,
            available=0,
            produced=(("purse", 6),),
            label="x",
        )

        assert MilitaryPolicy().decide(request, view=None) == GoldRushPolicy().decide(
            request, view=None
        )

    def test_it_chooses_actions_the_way_the_gold_rush_does(self):
        """Away from a battle it is the gold rush, so a turn it drives has to be the same turn."""
        session = _attacked(defenders={"guard": 4}, attackers={"raider": 3})
        view = project(session.game, ATTACKER)
        actions = session.legal_actions(ATTACKER)
        assert actions, "the attacker should hold priority in its own Battle phase"

        assert MilitaryPolicy().choose(view, actions) == GoldRushPolicy().choose(view, actions)


def test_a_driven_defense_puts_units_on_the_battlefield():
    """The whole path through the engine rather than the policy alone: the request the engine builds,
    answered through the session, leaves the Defender's unit standing where it was sent. A seat
    running the default agent answers the empty tuple here and the Province falls uncontested."""
    session = _attacked(defenders={"guard": 4}, attackers={"raider": 3}, provinces=1)
    game = session.game
    battle.declare_attack(game, ATTACKER)
    battle.open_maneuvers(game)
    session.submit(ATTACKER, DecisionResponse((assignment_token("raider", 0),)))

    request = game.pending
    assert isinstance(request, AssignUnits) and request.seat is DEFENDER
    session.submit(DEFENDER, MilitaryPolicy().decide(request, project(game, DEFENDER)))

    assert location_of(game.table, game.table.cards_by_id["guard"]).battlefield == 0
    assert battle.army_force(game, 0, DEFENDER) == 4
