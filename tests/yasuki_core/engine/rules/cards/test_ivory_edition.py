from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility, DeclareAttack, Pass
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_force, effective_personal_honor
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
    two_seat_game,
)


def test_haramaki_do_gives_its_personality_both_halves_of_what_it_says():
    """The +2F is printed on the card and needs no handler; the +1PH is text, and only the handler
    delivers it. A test asserting one half alone passes with the other half missing."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, personal_honor=2))
    attached(game, attachment("armor", printed_id="haramaki_do", force_modifier=2), "hero")

    assert effective_force(game, hero) == 4
    assert effective_personal_honor(game, hero) == 3


def test_the_granted_honor_leaves_when_the_armor_does():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, personal_honor=2))
    armor = attached(game, attachment("armor", printed_id="haramaki_do", force_modifier=2), "hero")

    ops.detach(game.table, armor)

    assert effective_personal_honor(game, hero) == 2


ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _archers_battle():
    """The Combat Segment of P1's attack, the Archers attached to the attacking Personality.

    The Defender brings a 2F Personality carrying a 2F Follower, so a Ranged 2 destroys either and
    a Fear 2 bows either.
    """
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("hero", owner=ATTACKER, force=4))
    attached(
        state,
        attachment(
            "archers",
            attachment_type=AttachmentType.FOLLOWER,
            force=2,
            printed_id="incendiary_archers",
        ),
        "hero",
    )
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    attached(
        state,
        attachment("ashigaru", owner=DEFENDER, attachment_type=AttachmentType.FOLLOWER, force=2),
        "guard",
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("hero@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    session.submit(ATTACKER, DecisionResponse(("0",)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    session.act(DEFENDER, Pass())
    return session


def _in_play(session, card_id):
    table = session.game.table
    return table.cards_by_id[card_id] in table.battlefield.cards


def test_both_of_the_archers_abilities_are_offered():
    """ "Battle, :bow:: :ranged: 2. Battle: :fear: 2." Both are Battle, so the designator says
    nothing about which is which and only the key tells them apart."""
    session = _archers_battle()

    offered = [
        action
        for action in session.legal_actions(ATTACKER)
        if isinstance(action, ActivateAbility) and action.card_id == "archers"
    ]

    assert offered == [
        ActivateAbility("archers", "ranged"),
        ActivateAbility("archers", "fear"),
    ]


def test_the_ranged_attack_bows_the_archers_and_destroys_its_target():
    session = _archers_battle()

    session.act(ATTACKER, ActivateAbility("archers", "ranged"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))

    assert not _in_play(session, "ashigaru")
    assert session.game.table.cards_by_id["archers"].bowed  # the :bow: it paid


def test_the_fear_bows_its_target_and_costs_nothing():
    """The second ability prints no cost, so the Archers stay standing — which is what makes taking
    the wrong one of the two a real mistake rather than a cosmetic one."""
    session = _archers_battle()

    session.act(ATTACKER, ActivateAbility("archers", "fear"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))

    assert _in_play(session, "ashigaru")  # Fear bows, it does not destroy
    assert session.game.table.cards_by_id["ashigaru"].bowed
    assert not session.game.table.cards_by_id["archers"].bowed


def test_a_keyed_archers_activation_replays():
    session = _archers_battle()
    session.act(ATTACKER, ActivateAbility("archers", "fear"))
    session.submit(ATTACKER, DecisionResponse(("ashigaru",)))

    assert replay(session.log) == session.game
