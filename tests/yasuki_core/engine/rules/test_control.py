from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.board.queries import owned_holdings, units_at
from yasuki_core.engine.rules.board.seats import cards_in_play
from yasuki_core.engine.rules.effects import Destroy
from yasuki_core.engine.rules.gold.production import complete_production
from yasuki_core.engine.rules.rulebook.recruit import meets_honor_requirement
from yasuki_core.engine.rules.triggers import (
    action_destroyed_personality,
    resolve_action_effects,
    resolve_effects,
)
from yasuki_core.engine.table import (
    BATTLEFIELD,
    BoardPos,
    Location,
    ZoneKey,
    ZoneRole,
    controller_of,
    location_of,
)
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    holding,
    personality,
    put_in_play,
    register,
    stronghold,
    two_seat_game,
)

P1, P2 = PlayerId.P1, PlayerId.P2


def _give_control(game, card_id: str, seat: PlayerId) -> None:
    """Hand ``card_id`` to ``seat``, as a Take control effect will once one exists."""
    game.table.controllers[card_id] = seat


def test_a_card_is_controlled_by_its_owner_until_control_passes():
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))

    assert controller_of(game.table, mine) is P1

    _give_control(game, "mine", P2)
    assert controller_of(game.table, mine) is P2


def test_an_attachment_is_controlled_by_its_personalitys_controller():
    """CR, Card control: an attached card in a unit is controlled by the unit's Personality's
    controller, so a Follower follows its master and never carries its own entry."""
    game = two_seat_game()
    put_in_play(game, personality("master"))
    attached(game, attachment("levy", attachment_type=AttachmentType.FOLLOWER), "master")
    levy = game.table.cards_by_id["levy"]

    _give_control(game, "master", P2)

    assert controller_of(game.table, levy) is P2
    assert game.table.controllers.get("levy") is None


def test_a_card_attached_to_a_province_is_controlled_by_the_provinces_owner():
    """CR, Card control: a Fortification or other card attached to a province is controlled by the
    player whose province it is."""
    game = two_seat_game()
    wall = put_in_play(game, personality("wall", owner=P1))
    ops.attach_to_province(game.table, wall, ZoneKey(P2, ZoneRole.PROVINCE, 0))

    assert controller_of(game.table, wall) is P2


def test_control_is_dropped_when_the_card_leaves_play():
    """Control is in-play state, and a card that comes back comes back controlled by whoever
    brought it in (CR, Card control)."""
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))
    _give_control(game, "mine", P2)

    resolve_effects(game, [Destroy("mine", P2)])

    assert game.table.controllers == {}
    assert controller_of(game.table, mine) is P1


def test_repositioning_a_controlled_card_on_the_table_keeps_its_controller():
    """Dragging a card about is presentation. Control is in-play state, so the move that re-adds a
    card to the battlefield has to carry it across the removal rather than drop it."""
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))
    _give_control(game, "mine", P2)

    ops.move_card(game.table, mine, BATTLEFIELD, position=BoardPos(0.5, 0.5))

    assert controller_of(game.table, mine) is P2


def test_a_destroyed_card_reaches_its_owners_pile_however_it_was_controlled():
    """Ownership never changes (CR, Card ownership), so the pile a card dies into is its owner's
    and not its controller's."""
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))
    _give_control(game, "mine", P2)

    resolve_effects(game, [Destroy("mine", P2)])

    assert mine.owner is P1
    piles = game.table.zones
    assert "mine" in {card.id for card in piles[ZoneKey(P1, ZoneRole.DYNASTY_DISCARD)].cards}
    assert piles[ZoneKey(P2, ZoneRole.DYNASTY_DISCARD)].cards == []


def test_the_cards_a_seat_has_in_play_follow_control():
    game = two_seat_game()
    put_in_play(game, personality("mine"))
    _give_control(game, "mine", P2)

    assert "mine" not in {card.id for card in cards_in_play(game, P1)}
    assert "mine" in {card.id for card in cards_in_play(game, P2)}
    assert "mine" in {card.id for card in units_at(game, None, P2)}
    assert units_at(game, None, P1) == []


def test_a_controlled_holding_pays_its_controller_rather_than_its_owner():
    """Only the controller of a card may use it to pay costs (CR, Card control)."""
    game = two_seat_game()
    put_in_play(game, holding("vault", gold_production=4))
    _give_control(game, "vault", P2)

    assert "vault" in {card.id for card in owned_holdings(game, P2)}
    complete_production(game, "vault", ())

    assert game.gold.get(P2, 0) == 4
    assert game.gold.get(P1, 0) == 0


def test_an_honor_requirement_is_measured_against_the_controllers_family_honor():
    """CR, Honor Requirement: a player cannot bring a Personality into play with one higher than
    his or her own Family Honor, and the player bringing it in is its controller."""
    game = two_seat_game()
    recruit = register(game.table, personality("recruit", owner=P1, honor_requirement=5))
    game.table.seats[P1].honor = 0
    game.table.seats[P2].honor = 9
    put_in_play(game, recruit)

    assert meets_honor_requirement(game, recruit) is False

    _give_control(game, "recruit", P2)
    assert meets_honor_requirement(game, recruit) is True


def test_the_honor_requirement_waiver_reads_the_controllers_lost_honor():
    """The latch waives the requirement of the seat's own Clan Alignment's Personalities, and both
    the latch and the alignment are the controller's."""
    game = two_seat_game()
    put_in_play(game, stronghold(P2, clan="Spider"))
    recruit = register(
        game.table, personality("recruit", owner=P1, honor_requirement=5, clans=("Spider",))
    )
    game.table.seats[P1].honor = 0
    game.table.seats[P2].honor = 0
    game.table.seats[P2].lost_honor_from_elsewhere = True
    put_in_play(game, recruit)

    assert meets_honor_requirement(game, recruit) is False

    _give_control(game, "recruit", P2)
    assert meets_honor_requirement(game, recruit) is True


def test_a_dishonorable_death_costs_the_controller_the_honor_rather_than_the_owner():
    """The card has left play by the time the loss is worked out, so its controller comes from the
    record of how it stood as it went."""
    game = two_seat_game()
    shamed = put_in_play(game, personality("shamed", personal_honor=2))
    shamed.dishonor()
    _give_control(game, "shamed", P2)

    resolve_effects(game, [Destroy("shamed", P2)])

    assert game.table.seats[P2].honor == -2
    assert game.table.seats[P1].honor == 0


def test_what_the_action_destroyed_is_read_against_the_controller_who_lost_it():
    """A card destroyed while controlled by another seat is that seat's loss, which is what "if the
    action destroyed your Personality" asks."""
    game = two_seat_game()
    put_in_play(game, personality("mine"))
    _give_control(game, "mine", P2)

    resolve_action_effects(game, [Destroy("mine", P2)])

    assert action_destroyed_personality(game, P2) is True
    assert action_destroyed_personality(game, P1) is False


def test_a_controlled_card_with_no_recorded_place_stands_in_its_controllers_home():
    """CR, Card control: a card whose control passes enters the new player's home."""
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))
    assert location_of(game.table, mine) == Location.home(P1)

    _give_control(game, "mine", P2)

    assert location_of(game.table, mine) == Location.home(P2)
