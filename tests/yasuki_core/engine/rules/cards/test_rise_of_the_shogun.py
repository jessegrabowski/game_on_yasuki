from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.abilities.costs import bow_cost
from yasuki_core.engine.rules.effects import Bow
from yasuki_core.engine.rules.units.membership import attachments_of
from yasuki_core.engine.rules.vocabulary.actions import (
    ActivateAbility,
    DeclareAttack,
    Pass,
    PlayStrategy,
)
from yasuki_core.engine.rules.cards.onyx_edition import CAVALRY_FOLLOWER
from yasuki_core.engine.rules.vocabulary.decisions import Confirm, DecisionResponse
from yasuki_core.engine.session import EngineSession
from yasuki_core.engine.table import TableState, ZoneKey, ZoneRole, location_of
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import ActionPrint
from yasuki_core.game_pieces.constants import Side
from yasuki_core.engine.rules.stats.card_values import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)

from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    token_template,
    attachment,
    end_phase,
    holding,
    pay,
    personality,
    province_card,
    put_in_play,
    register,
    two_seat_game,
)


def test_shadowlands_ambassador_dishonors_the_personality_he_serves():
    """He prints Force 2 and Chi -1 and reads "This Personality has -1PH". The Force is his own and
    stays with the unit. The Chi and the Honor are both the Personality's."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=3, chi=2, personal_honor=2))
    attached(
        game,
        attachment(
            "ambassador",
            printed_id="shadowlands_ambassador",
            attachment_type=AttachmentType.FOLLOWER,
            force=2,
            chi_modifier=-1,
        ),
        "hero",
    )

    assert effective_force(game, hero) == 3
    assert effective_chi(game, hero) == 1
    assert effective_personal_honor(game, hero) == 1


# --- Shadowlands Ambassador's bow waiver ---

P1 = PlayerId.P1


def _gorou_game(*, ambassador=True):
    """Utaku Gorou, whose Open ability costs a bow, with the Ambassador on him to waive it."""
    game = two_seat_game()
    token_template(
        game, CAVALRY_FOLLOWER, name="Cavalry", card_type="Follower", keywords=("Cavalry",), force=1
    )
    put_in_play(
        game,
        personality(
            "gorou", printed_id="utaku_gorou_stablemaster", force=2, chi=2, keywords=("Samurai",)
        ),
    )
    put_in_play(game, personality("bushi", force=3, chi=2, keywords=("Samurai",)))
    if ambassador:
        attached(
            game,
            attachment(
                "ambassador",
                printed_id="shadowlands_ambassador",
                attachment_type=AttachmentType.FOLLOWER,
                force=2,
                chi_modifier=-1,
            ),
            "gorou",
        )
    return EngineSession.start(game.table, P1)


def test_paying_a_bow_cost_offers_the_waiver_first():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))

    pending = session.game.pending
    assert isinstance(pending, Confirm)
    assert pending.question == "Ignore the cost of bowing gorou?"


def test_taking_the_waiver_leaves_him_standing_and_still_resolves():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("ambassador",)))  # yes: ignore the cost
    session.submit(P1, DecisionResponse(("bushi",)))

    game = session.game
    assert game.table.cards_by_id["gorou"].bowed is False
    assert attachments_of(game, game.table.cards_by_id["bushi"])[0].name == "Cavalry"


def test_declining_the_waiver_pays_the_cost_as_printed():
    session = _gorou_game()

    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(()))  # no: bow him
    session.submit(P1, DecisionResponse(("bushi",)))

    assert session.game.table.cards_by_id["gorou"].bowed is True


def test_the_waiver_is_offered_once_a_turn():
    """Spent on the first ability, a second bow cost the same turn is charged as printed with
    nothing to ask about. Gorou's own ability is once per turn too, so the cost is built directly."""
    session = _gorou_game()
    session.act(P1, ActivateAbility("gorou"))
    session.submit(P1, DecisionResponse(("ambassador",)))
    session.submit(P1, DecisionResponse(("bushi",)))
    gorou = session.game.table.cards_by_id["gorou"]
    gorou.unbow()

    assert bow_cost(session.game, gorou) == [Bow("gorou")]


def test_merely_listing_the_action_does_not_spend_the_waiver():
    """A cost is built to decide legality as well as to pay, so looking must not spend the use."""
    session = _gorou_game()

    session.legal_actions(P1)
    session.legal_actions(P1)
    session.act(P1, ActivateAbility("gorou"))

    assert isinstance(session.game.pending, Confirm)


def test_a_personality_without_the_ambassador_is_asked_nothing():
    session = _gorou_game(ambassador=False)

    session.act(P1, ActivateAbility("gorou"))

    assert not isinstance(session.game.pending, Confirm)
    assert session.game.table.cards_by_id["gorou"].bowed is True


# --- Rout ---

ATTACKER, DEFENDER = PlayerId.P1, PlayerId.P2


def _rout_battle() -> EngineSession:
    """The Combat Segment of P1's attack, with Rout in the Defender's hand. The Attacker sends a
    Personality carrying an Item and a Follower, and the Defender sends a plain one."""
    state = TableState.empty_two_seat()
    province_card(state, "atk-prov0", seat=ATTACKER, index=0)
    province_card(state, "def-prov0", seat=DEFENDER, index=0)
    put_in_play(state, holding("mine", owner=DEFENDER, gold_production=2))
    put_in_play(state, personality("raider", owner=ATTACKER, force=3))
    attached(state, attachment("naginata", force_modifier=1), "raider")
    attached(
        state,
        attachment("ashigaru", attachment_type=AttachmentType.FOLLOWER, force=1),
        "raider",
    )
    put_in_play(state, personality("guard", owner=DEFENDER, force=2))
    state.zones[ZoneKey(DEFENDER, ZoneRole.HAND)].add(
        register(
            state,
            L5RCard.of(
                ActionPrint,
                id="rout",
                name="Rout",
                printed_id="rout",
                side=Side.FATE,
                owner=DEFENDER,
                gold_cost=1,
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


def _play_rout(session: EngineSession) -> tuple[str, ...]:
    session.act(DEFENDER, PlayStrategy("rout"))
    pay(session, DEFENDER)
    return session.game.pending.candidates


def test_rout_targets_a_unit_on_either_side():
    """A unit is a Personality and what is attached to him (CR, Unit), and the card names no side."""
    session = _rout_battle()

    assert set(_play_rout(session)) == {"raider", "guard"}


def test_the_targeted_unit_goes_home_and_loses_the_chosen_attachment():
    session = _rout_battle()
    _play_rout(session)

    session.submit(DEFENDER, DecisionResponse(("raider",)))
    session.submit(DEFENDER, DecisionResponse(("naginata",)))

    game = session.game
    raider = game.table.cards_by_id["raider"]
    assert location_of(game.table, raider).is_home
    assert [card.id for card in attachments_of(game, raider)] == ["ashigaru"]


def test_the_seat_playing_it_chooses_among_the_units_attachments():
    session = _rout_battle()
    _play_rout(session)

    session.submit(DEFENDER, DecisionResponse(("raider",)))

    pending = session.game.pending
    assert pending.seat is DEFENDER
    assert set(pending.candidates) == {"naginata", "ashigaru"}


def test_a_unit_carrying_nothing_only_goes_home():
    session = _rout_battle()
    _play_rout(session)

    session.submit(DEFENDER, DecisionResponse(("guard",)))

    game = session.game
    assert location_of(game.table, game.table.cards_by_id["guard"]).is_home
    assert game.pending is None
