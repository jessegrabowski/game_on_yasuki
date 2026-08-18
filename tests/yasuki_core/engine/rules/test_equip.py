from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_weapon_limit
from yasuki_core.engine.rules.equip import equip_targets, may_attach_weapon, weapons_on
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import (
    attached,
    attachment,
    personality,
    put_in_play,
    two_seat_game,
)

P1 = PlayerId.P1


def _weapon(card_id: str, *, two_handed: bool = False):
    keywords = ("Weapon", "Two-Handed") if two_handed else ("Weapon",)
    return attachment(card_id, keywords=keywords)


def test_a_personality_carries_one_weapon_by_default():
    """The limit is a characteristic rather than a rule with an exception list, so it reads like any
    other number on the card (CR, Weapon)."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))

    assert effective_weapon_limit(game, hero) == 1


def test_a_kensai_carries_two():
    """Kensai raises the limit; it does not exempt him from it (CR, Kensai)."""
    game = two_seat_game()
    kensai = put_in_play(game, personality("kensai", keywords=("Kensai",)))

    assert effective_weapon_limit(game, kensai) == 2


def test_a_second_weapon_is_refused_at_the_limit():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, _weapon("katana"), "hero")

    assert may_attach_weapon(game, hero, _weapon("wakizashi")) is False


def test_a_kensai_takes_a_second_weapon_but_not_a_third():
    game = two_seat_game()
    kensai = put_in_play(game, personality("kensai", keywords=("Kensai",)))
    attached(game, _weapon("katana"), "kensai")

    assert may_attach_weapon(game, kensai, _weapon("wakizashi")) is True

    attached(game, _weapon("wakizashi"), "kensai")
    assert may_attach_weapon(game, kensai, _weapon("tanto")) is False


def test_a_two_handed_weapon_needs_an_empty_hand_even_for_a_kensai():
    """ "A Personality, even a Kensai, cannot attach a Two-Handed Weapon if they have a Weapon
    attached" — so the count is not the only rule, and raising it does not lift this one."""
    game = two_seat_game()
    kensai = put_in_play(game, personality("kensai", keywords=("Kensai",)))
    attached(game, _weapon("katana"), "kensai")

    assert may_attach_weapon(game, kensai, _weapon("no-dachi", two_handed=True)) is False


def test_nothing_joins_a_two_handed_weapon_even_for_a_kensai():
    """The other direction of the same rule: "cannot attach a Weapon if they have a Two-Handed
    Weapon attached"."""
    game = two_seat_game()
    kensai = put_in_play(game, personality("kensai", keywords=("Kensai",)))
    attached(game, _weapon("no-dachi", two_handed=True), "kensai")

    assert may_attach_weapon(game, kensai, _weapon("wakizashi")) is False


def test_an_empty_handed_personality_takes_a_two_handed_weapon():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))

    assert may_attach_weapon(game, hero, _weapon("no-dachi", two_handed=True)) is True


def test_a_non_weapon_item_does_not_fill_a_weapon_slot():
    """The limit counts Weapons, not attachments — armor and Followers leave the hand free."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, attachment("armor", keywords=("Armor",)), "hero")
    attached(
        game, attachment("guard", attachment_type=AttachmentType.FOLLOWER, keywords=()), "hero"
    )

    assert weapons_on(game, hero) == ()
    assert may_attach_weapon(game, hero, _weapon("katana")) is True


def test_a_follower_is_not_held_back_by_a_weapon_the_personality_already_carries():
    """The Weapon count is a rule about Weapons. Applying it to every attachment would stop a
    Personality holding a katana from ever taking a Follower."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, _weapon("katana"), "hero")

    assert equip_targets(game, attachment("ashigaru", keywords=("Follower",))) == (hero,)
    assert equip_targets(game, _weapon("wakizashi")) == ()


def test_an_effect_can_raise_the_limit_like_any_other_characteristic():
    """What modelling the limit as a number buys: an Event granting an extra Weapon is a modifier,
    not a second exception baked beside Kensai."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, _weapon("katana"), "hero")
    assert may_attach_weapon(game, hero, _weapon("wakizashi")) is False

    game.modifiers.append(
        Modifier("event", hero.id, Stat.WEAPON_LIMIT, 1, Duration.UNTIL_END_OF_TURN)
    )

    assert effective_weapon_limit(game, hero) == 2
    assert may_attach_weapon(game, hero, _weapon("wakizashi")) is True
