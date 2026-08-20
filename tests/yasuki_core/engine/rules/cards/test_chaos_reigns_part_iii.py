from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.actions import ActivateAbility
from yasuki_core.engine.rules.attachments import attachments_of
from yasuki_core.engine.rules.cards.chaos_reigns_part_iii import FUSHICHO, ZOMBIE_FOLLOWER
from yasuki_core.engine.rules.decisions import DecisionResponse
from yasuki_core.engine.rules.economy import effective_force
from yasuki_core.engine.rules.events import EnteredPlay
from yasuki_core.engine.rules.log import replay
from yasuki_core.engine.rules.triggers import fire
from yasuki_core.engine.session import EngineSession

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    end_turn,
    holding,
    personality,
    put_in_play,
    token_template,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


# --- Kengun Grounds ---


def _kengun_game():
    """The Grounds in play beside a tainted Personality and a clean one."""
    game = two_seat_game()
    token_template(
        game,
        ZOMBIE_FOLLOWER,
        name="Zombie Follower",
        card_type="Follower",
        keywords=("Nonhuman", "Shadowlands", "Undead"),
        force=1,
    )
    put_in_play(game, holding("grounds", printed_id="kengun_grounds", name="Kengun Grounds"))
    put_in_play(game, personality("tainted", force=2, chi=3, keywords=("Shadowlands",)))
    put_in_play(game, personality("clean", force=2, chi=3, keywords=("Samurai",)))
    return EngineSession.start(game.table, P1)


def test_kengun_grounds_costs_two_honor_to_open():
    session = _kengun_game()

    fire(session.game, EnteredPlay("grounds"))

    assert session.game.table.seats[P1].honor == -2


def test_kengun_grounds_raises_a_zombie_for_a_shadowlands_personality():
    session = _kengun_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("tainted",)))

    game = session.game
    zombie = attachments_of(game, game.table.cards_by_id["tainted"])[0]
    assert zombie.name == "Zombie Follower"
    assert game.table.cards_by_id["grounds"].bowed is True  # the cost
    assert game.table.seats[P1].honor == 0  # a tainted master pays nothing extra


def test_giving_the_zombie_to_an_untainted_personality_costs_five_honor():
    session = _kengun_game()

    session.act(P1, ActivateAbility("grounds"))
    session.submit(P1, DecisionResponse(("clean",)))

    assert attachments_of(session.game, session.game.table.cards_by_id["clean"])
    assert session.game.table.seats[P1].honor == -5


def test_kengun_grounds_is_withheld_on_another_seats_turn():
    """ "If it is your turn" — read before the ability is offered rather than resolving to nothing."""
    session = _kengun_game()
    end_turn(session)  # hand the turn to P2; the Grounds is still P1's to bow

    assert session.game.active is P2
    assert ActivateAbility("grounds") not in session.legal_actions(P1)


# --- Walk with Tengoku ---


def _tengoku_game():
    """The Spell on a Shugenja, ready to bow."""
    game = two_seat_game()
    token_template(
        game,
        FUSHICHO,
        name="Fushicho",
        card_type="Personality",
        keywords=("Cavalry", "Fire", "Fushicho", "Nonhuman"),
        force=3,
        chi=2,
    )
    put_in_play(game, personality("shugenja", force=1, chi=4, keywords=("Shugenja",)))
    attached(game, attachment("spell", printed_id="walk_with_tengoku"), "shugenja")
    return EngineSession.start(game.table, P1)


def _fushicho_of(session):
    return next(card for card in session.game.table.battlefield.cards if card.is_token)


def test_walk_with_tengoku_calls_a_fushicho():
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))

    fushicho = _fushicho_of(session)
    assert fushicho.name == "Fushicho"
    assert effective_force(session.game, fushicho) == 3
    assert session.game.table.cards_by_id["spell"].bowed is True  # the cost bows the Spell


def test_the_fushicho_burns_out_before_the_turn_ends():
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))
    fushicho = _fushicho_of(session)
    end_turn(session)

    assert fushicho.id not in session.game.table.cards_by_id


def test_walk_with_tengoku_asks_for_no_target():
    """The Spell names none, so announcing it resolves the whole thing."""
    session = _tengoku_game()

    session.act(P1, ActivateAbility("spell"))

    assert session.game.pending is None


def test_walk_with_tengoku_replays_to_the_same_board():
    session = _tengoku_game()
    session.act(P1, ActivateAbility("spell"))

    assert replay(session.log).table == session.game.table
