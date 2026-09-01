import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import DeclareAttack, Pass, PlayStrategy
from yasuki_core.engine.rules.attachments import attachments_of
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
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    token_template,
)

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _refugees_battle(
    *, holder: PlayerId = DEFENDER, defender_gold: int = 2, attacker_gold: int = 0
) -> EngineSession:
    """The Combat Segment of P1's attack, with Refugees in ``holder``'s hand. The Attacker sends a
    plain Personality; the Defender sends one carrying a Follower and keeps one at home."""
    state = TableState.empty_two_seat()
    token_template(
        state, "ashigaru_2", name="Ashigaru", card_type="Follower", keywords=("Ashigaru",), force=1
    )
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, holding("mine", owner=DEFENDER, gold_production=defender_gold))
    put_in_play(state, holding("quarry", owner=ATTACKER, gold_production=attacker_gold))
    put_in_play(state, personality("raider", owner=ATTACKER, force=3))
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    put_in_play(state, personality("escort", owner=DEFENDER, force=1))
    attached(state, attachment("yari", attachment_type=AttachmentType.FOLLOWER, force=1), "escort")
    state.zones[ZoneKey(holder, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="refugees",
                name="Refugees",
                printed_id="refugees",
                side=Side.FATE,
                owner=holder,
            ),
        )
    )
    session = EngineSession.start(state, ATTACKER)
    end_phase(session)
    session.act(ATTACKER, DeclareAttack())
    session.submit(ATTACKER, DecisionResponse(("raider@0",)))
    session.submit(DEFENDER, DecisionResponse(("guard@0", "escort@0")))
    choice = session.game.pending
    session.submit(choice.seat, DecisionResponse((choice.candidates[0],)))
    return session


def _reach_the_combat_segment(session: EngineSession, holder: PlayerId) -> None:
    """Pass out of the Engage Segment and hand the opportunity to ``holder``."""
    session.act(DEFENDER, Pass())
    session.act(ATTACKER, Pass())
    if holder is ATTACKER:
        session.act(DEFENDER, Pass())


def _offered_targets(session: EngineSession, holder: PlayerId) -> tuple[str, ...]:
    session.act(holder, PlayStrategy("refugees"))
    session.submit(holder, DecisionResponse())
    return session.game.pending.candidates


def test_refugees_targets_only_personalities_carrying_no_follower():
    """ "A Personality without Followers" — either side's, since the card names no side. The escort
    has a Follower, so he is spared."""
    session = _refugees_battle()
    _reach_the_combat_segment(session, DEFENDER)

    assert set(_offered_targets(session, DEFENDER)) == {"raider", "guard"}


def test_the_target_goes_home_and_bows():
    session = _refugees_battle()
    _reach_the_combat_segment(session, DEFENDER)
    _offered_targets(session, DEFENDER)

    session.submit(DEFENDER, DecisionResponse(("raider",)))

    raider = session.game.table.cards_by_id["raider"]
    assert location_of(session.game.table, raider).is_home
    assert raider.bowed


def test_paying_the_gold_buys_the_ashigaru():
    session = _refugees_battle()
    _reach_the_combat_segment(session, DEFENDER)
    _offered_targets(session, DEFENDER)
    session.submit(DEFENDER, DecisionResponse(("guard",)))

    session.submit(DEFENDER, DecisionResponse(("guard",)))  # yes to the offer
    pay(session, DEFENDER)

    guard = session.game.table.cards_by_id["guard"]
    assert [card.name for card in attachments_of(session.game, guard)] == ["Ashigaru"]


def test_the_offer_goes_to_the_targets_controller_not_the_seat_playing_it():
    """ "The target's controller may pay" — the Defender plays Refugees at an attacking Personality,
    and it is the Attacker who is asked."""
    session = _refugees_battle(attacker_gold=2)
    _reach_the_combat_segment(session, DEFENDER)
    _offered_targets(session, DEFENDER)

    session.submit(DEFENDER, DecisionResponse(("raider",)))

    assert session.game.pending.seat is ATTACKER


def test_declining_the_ashigaru_costs_nothing():
    session = _refugees_battle()
    _reach_the_combat_segment(session, DEFENDER)
    _offered_targets(session, DEFENDER)
    session.submit(DEFENDER, DecisionResponse(("guard",)))
    before = session.game.gold[DEFENDER]

    session.submit(DEFENDER, DecisionResponse())

    guard = session.game.table.cards_by_id["guard"]
    assert attachments_of(session.game, guard) == ()
    assert session.game.gold[DEFENDER] == before


def test_the_offer_is_withheld_from_a_controller_who_could_not_pay():
    """ "May pay 1 Gold" is no offer at all to a seat with none to reach."""
    session = _refugees_battle(defender_gold=0)
    _reach_the_combat_segment(session, DEFENDER)
    _offered_targets(session, DEFENDER)

    session.submit(DEFENDER, DecisionResponse(("guard",)))

    assert session.game.pending is None


@pytest.mark.parametrize(
    "holder, standing_there",
    [(DEFENDER, ("guard", "escort")), (ATTACKER, ("raider",))],
    ids=["defender", "attacker"],
)
def test_it_is_played_with_no_units_at_the_battlefield(holder, standing_there):
    """ "Absent Battle" is the plain designator, so the exception is not conditioned on which side of
    the battle the seat is on."""
    session = _refugees_battle(holder=holder)
    _reach_the_combat_segment(session, holder)
    table = session.game.table
    for card_id in standing_there:
        ops.return_home(table, table.cards_by_id[card_id])

    assert PlayStrategy("refugees") in session.legal_actions(holder)
