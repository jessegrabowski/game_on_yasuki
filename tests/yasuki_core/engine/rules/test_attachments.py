from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import attached_to, attachments_of
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.engine.zones import ProvinceZone
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1


def test_an_attached_card_names_the_card_it_hangs_on():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    item = attached(game, attachment("item"), "hero")

    assert attached_to(game, item) is hero


def test_a_card_hanging_on_nothing_names_nothing():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))

    assert attached_to(game, hero) is None


def test_a_personality_lists_every_card_attached_to_him():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    item = attached(game, attachment("item"), "hero")
    follower = attached(
        game, attachment("follower", attachment_type=AttachmentType.FOLLOWER), "hero"
    )

    assert attachments_of(game, hero) == (item, follower)


def test_a_personality_with_nothing_on_him_lists_nothing():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    rival = put_in_play(game, personality("rival"))
    attached(game, attachment("item"), rival.id)

    assert attachments_of(game, hero) == ()


def test_only_the_cards_directly_attached_are_listed():
    """An Item on a Follower belongs to the Follower. Step 4's unit total is what walks the chain;
    this reader deliberately does not, so a caller cannot double-count by accident."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    follower = attached(
        game, attachment("follower", attachment_type=AttachmentType.FOLLOWER), "hero"
    )
    item = attached(game, attachment("item"), "follower")

    assert attachments_of(game, hero) == (follower,)
    assert attachments_of(game, follower) == (item,)
    assert attached_to(game, item) is follower


def test_a_card_attached_to_a_province_hangs_on_no_card():
    """The graph holds Province attachments too — a Fortification or Region sits on a `ZoneKey`, not
    a card — so a reader that assumed every parent was a card id would raise here."""
    game = two_seat_game()
    game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1)
    wall = attached(game, attachment("wall"), ZoneKey(P1, ZoneRole.PROVINCE, 0))

    assert attached_to(game, wall) is None
