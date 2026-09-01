from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import DeclareAttack, Pass, PlayStrategy
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import ActionPrint

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_phase,
    personality,
    province_card,
    put_in_play,
    register,
)

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _incapacitated_battle(*, holder: PlayerId = ATTACKER) -> EngineSession:
    """The Combat Segment of P1's attack, with Incapacitated in ``holder``'s hand.

    The Defender sends one Personality carrying a Follower and keeps another at home, so the card's
    "defending" can be told from "the Defender's".
    """
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, personality("raider", owner=ATTACKER, force=3))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    put_in_play(state, personality("reserve", owner=DEFENDER, force=1))
    attached(state, attachment("yari", attachment_type=AttachmentType.FOLLOWER, force=1), "guard")
    state.zones[ZoneKey(holder, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="incapacitated",
                name="Incapacitated",
                printed_id="incapacitated",
                side=Side.FATE,
                owner=holder,
            ),
        )
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("raider@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0",)))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    return session


def _offered_targets(session: EngineSession, holder: PlayerId) -> tuple[str, ...]:
    session.act(holder, PlayStrategy("incapacitated"))
    session.submit(holder, DecisionResponse())
    return session.game.pending.candidates


def test_it_targets_the_defending_army_and_not_the_defenders_whole_side():
    """ "A target defending Personality" is the Defender's units at the battle, so the one kept at
    home is no target — and neither is the Attacker's own."""
    session = _incapacitated_battle()
    session.act(DEFENDER, Pass())

    assert set(_offered_targets(session, ATTACKER)) == {"guard"}


def test_the_target_goes_home():
    session = _incapacitated_battle()
    session.act(DEFENDER, Pass())
    _offered_targets(session, ATTACKER)

    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert location_of(session.game.table, session.game.table.cards_by_id["guard"]).is_home


def test_the_targets_follower_goes_home_with_him():
    """Moving a Personality moves his unit (CR, Unit), so a Follower is not left standing alone at
    a battlefield its Personality has left."""
    session = _incapacitated_battle()
    session.act(DEFENDER, Pass())
    _offered_targets(session, ATTACKER)

    session.submit(ATTACKER, DecisionResponse(("guard",)))

    assert location_of(session.game.table, session.game.table.cards_by_id["yari"]).is_home


def test_the_target_stops_counting_toward_the_defending_force():
    """The point of the card. The armies are level at 3 — the raider against the guard and his
    Follower — so the battle ties if the move does not take the guard out of the army it resolves,
    and the Attacker takes the Province if it does."""
    session = _incapacitated_battle()
    session.act(DEFENDER, Pass())
    _offered_targets(session, ATTACKER)
    session.submit(ATTACKER, DecisionResponse(("guard",)))

    # The Defender is not offered the rest of the segment: moving its only unit home left it with
    # no presence at the battle (CR, Rule of Presence).
    session.act(ATTACKER, Pass())

    outcome = session.game.attack.battlefields[0].outcome
    assert outcome.winner is ATTACKER


def test_the_defender_playing_it_still_reaches_only_the_defending_army():
    """The card names a side of the battle rather than the enemy of whoever plays it, so a Defender
    holding it can only point it at its own units."""
    session = _incapacitated_battle(holder=DEFENDER)

    assert set(_offered_targets(session, DEFENDER)) == {"guard"}
