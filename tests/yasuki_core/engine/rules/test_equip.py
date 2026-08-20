from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.economy import effective_weapon_limit
from yasuki_core.engine.rules.effects import AttachCard
from yasuki_core.engine.rules.equip import (
    creation_targets,
    equip_targets,
    may_attach_weapon,
    weapons_on,
)
from yasuki_core.engine.rules.modifiers import Duration, Modifier, Stat
from yasuki_core.engine.table import ZoneKey, ZoneRole
from yasuki_core.game_pieces.constants import AttachmentType, Side
from yasuki_core.game_pieces.prints import AttachmentPrint

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


def _weapon_print(*, two_handed: bool = False) -> AttachmentPrint:
    """The template a card creates a Weapon from — what the Weapon rules have to judge before there
    is a card to ask."""
    keywords = ("Weapon", "Two-Handed") if two_handed else ("Weapon",)
    return AttachmentPrint(
        name="Created Sword",
        side=Side.FATE,
        printed_id="created_sword",
        attachment_type=AttachmentType.ITEM,
        keywords=keywords,
        force_modifier=2,
    )


def test_a_created_weapon_answers_to_the_same_limit_as_a_drawn_one():
    """The rule is about the Personality's hands, not about where the Weapon came from, so a card
    that creates one has to be judged before it exists."""
    game = two_seat_game()
    free = put_in_play(game, personality("free"))
    put_in_play(game, personality("laden"))
    attached(game, _weapon("katana"), "laden")

    assert creation_targets(game, P1, _weapon_print()) == (free,)


def test_a_created_weapon_cannot_join_a_two_handed_one_even_for_a_kensai():
    """The Kensai's second slot is open, and Two-Handed exclusivity closes it anyway (CR,
    Two-Handed) — the branch a one-Weapon limit alone would never reach."""
    game = two_seat_game()
    kensai = put_in_play(game, personality("kensai", keywords=("Kensai",)))
    attached(game, _weapon("no_dachi", two_handed=True), "kensai")

    assert effective_weapon_limit(game, kensai) == 2
    assert creation_targets(game, P1, _weapon_print()) == ()


def test_a_created_follower_is_not_held_back_by_a_weapon():
    """A Follower answers to neither Weapon rule, however full the Personality's hands are."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, _weapon("katana"), "hero")
    ashigaru = AttachmentPrint(
        name="Ashigaru",
        side=Side.FATE,
        printed_id="ashigaru_2",
        attachment_type=AttachmentType.FOLLOWER,
        force=1,
    )

    assert creation_targets(game, P1, ashigaru) == (hero,)


def test_a_creation_only_reaches_its_own_seats_personalities():
    game = two_seat_game()
    mine = put_in_play(game, personality("mine"))
    put_in_play(game, personality("theirs", owner=PlayerId.P2))

    assert creation_targets(game, P1, _weapon_print()) == (mine,)


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


def test_attaching_as_an_effect_costs_nothing_and_asks_nothing():
    """The distinction the CR draws: an effect that "attaches" reaches the same board as the Equip
    action without its cost, its timing or its legality. Collapsing the two would silently charge
    gold for every card that says "attach"."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    katana = attachment("katana", keywords=("Weapon",))
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(katana)
    game.table.cards_by_id[katana.id] = katana
    gold_before = dict(game.gold)

    events = AttachCard(katana.id, hero.id).perform(game)

    assert game.table.units == {katana.id: hero.id}
    assert katana in game.table.battlefield.cards
    assert game.gold == gold_before
    assert [event.card_id for event in events] == [katana.id]


def test_attaching_a_card_already_in_play_moves_it_without_re_entering():
    """A card changing units has not entered play, so nothing may react as though it had."""
    game = two_seat_game()
    first = put_in_play(game, personality("first"))
    second = put_in_play(game, personality("second"))
    katana = attached(game, attachment("katana", keywords=("Weapon",)), "first")

    events = AttachCard(katana.id, second.id).perform(game)

    assert game.table.units == {katana.id: second.id}
    assert events == []
    assert first is not None  # the old host keeps its place on the board


def test_attaching_ignores_the_weapon_limit_that_equip_enforces():
    """`AttachCard` is the mechanical result, not the procedure: the restrictions live in Equip's
    legality, so an effect reaching past it is doing what the card told it to."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    attached(game, attachment("first", keywords=("Weapon",)), "hero")
    second = attachment("second", keywords=("Weapon",))
    game.table.cards_by_id[second.id] = second
    game.table.zones[ZoneKey(P1, ZoneRole.HAND)].add(second)
    assert may_attach_weapon(game, hero, second) is False

    AttachCard(second.id, hero.id).perform(game)

    assert game.table.units == {"first": hero.id, "second": hero.id}
