import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.attachments import (
    ATTACHMENT_GRANTS,
    attached_to,
    attachment_grant,
    attachments_of,
)
from yasuki_core.engine.rules.economy import (
    effective_chi,
    effective_force,
    effective_personal_honor,
)
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


def test_a_unit_is_flat_however_the_table_renders_it():
    """Everything in a unit attaches to the Personality (CR, Attachments). A card stacked behind a
    Follower for rendering is still the Personality's, and the rules layer reads the relation rather
    than the stacking."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=1))
    follower = attached(
        game, attachment("follower", attachment_type=AttachmentType.FOLLOWER, force=5), "hero"
    )
    item = attached(game, attachment("item", force_modifier=2), "hero")
    ops.attach(game.table, item, follower.id)  # renders behind the Follower, rules-irrelevant

    assert attachments_of(game, hero) == (follower, item)
    assert attached_to(game, item) is hero
    assert attachments_of(game, follower) == ()
    assert effective_force(game, hero) == 3


def test_a_non_personality_cannot_be_attached_to():
    """The relation cannot represent it, so the mistake is refused where it is made rather than
    surviving as a board state the rules layer has to defend against."""
    game = two_seat_game()
    put_in_play(game, personality("hero"))
    follower = attached(
        game, attachment("follower", attachment_type=AttachmentType.FOLLOWER), "hero"
    )
    item = put_in_play(game, attachment("item"))

    with pytest.raises(ValueError, match="non-Personality"):
        ops.attach_to_personality(game.table, item, follower)


def test_a_card_on_a_province_is_in_no_unit():
    """A Region or Fortification is attached to a Province, which is its own relation. Reading it
    through the unit relation must not find a Personality, and must not raise."""
    game = two_seat_game()
    game.table.zones[ZoneKey(P1, ZoneRole.PROVINCE, 0)] = ProvinceZone(owner=P1)
    wall = attached(game, attachment("wall"), ZoneKey(P1, ZoneRole.PROVINCE, 0))

    assert attached_to(game, wall) is None


def test_a_parent_that_left_the_table_is_loud_rather_than_silent():
    """`ops` drops the entry when a card leaves the battlefield, so this state is unreachable — and
    answering None for it would read exactly like an unattached card, hiding a broken invariant
    behind a legitimate answer."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    item = attached(game, attachment("item"), "hero")
    del game.table.cards_by_id[hero.id]

    with pytest.raises(KeyError):
        attached_to(game, item)


def test_an_attachments_modifier_reaches_the_personality():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, chi=3))
    attached(game, attachment("item", force_modifier=1, chi_modifier=2), "hero")

    assert effective_force(game, hero) == 3
    assert effective_chi(game, hero) == 5


def test_a_stat_the_attachment_has_of_its_own_stays_with_it():
    """A Follower's Force stands in the unit and totals into the army at step 4. Folding it into the
    Personality's own Force here would double-count it there."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2))
    attached(
        game,
        attachment("follower", attachment_type=AttachmentType.FOLLOWER, force=5),
        "hero",
    )

    assert effective_force(game, hero) == 2


def test_one_card_can_have_a_stat_and_grant_a_modifier_at_once():
    """The two halves are independent fields, so a card carrying a Force of its own can still move
    the Personality's Chi."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2, chi=3))
    attached(
        game,
        attachment("follower", attachment_type=AttachmentType.FOLLOWER, force=2, chi_modifier=-1),
        "hero",
    )

    assert effective_force(game, hero) == 2
    assert effective_chi(game, hero) == 2


def test_the_modifier_leaves_with_the_card():
    """It is derived from the relation, so detaching removes it without anything having to revoke
    it."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2))
    item = attached(game, attachment("item", force_modifier=1), "hero")
    assert effective_force(game, hero) == 3

    ops.detach_from_parent(game.table, item)

    assert effective_force(game, hero) == 2


def test_modifiers_from_several_attachments_stack():
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", force=2))
    attached(game, attachment("item", force_modifier=1), "hero")
    attached(game, attachment("armor", force_modifier=3), "hero")

    assert effective_force(game, hero) == 6


def test_penalties_are_summed_before_the_floor_applies():
    """Two penalties against a Chi of 1 total -1, which reads as 0 — the sum floors once, rather than
    each penalty flooring on its own (CR, Calculating Stats)."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero", chi=1))
    attached(game, attachment("item", chi_modifier=-1), "hero")
    attached(game, attachment("curse", chi_modifier=-1), "hero")

    assert effective_chi(game, hero) == 0


def test_a_second_attachment_grant_for_one_card_is_refused():
    # The dict would overwrite, leaving no trace of the handler that lost — so the check has to be at
    # registration, not on the registry afterwards.
    @attachment_grant("guard_probe")
    def _first(game, card, host):
        return {}

    try:
        with pytest.raises(ValueError, match="guard_probe already has an attachment grant"):

            @attachment_grant("guard_probe")
            def _second(game, card, host):
                return {}
    finally:
        ATTACHMENT_GRANTS.pop("guard_probe", None)


def test_a_personal_honor_counter_reaches_the_cards_honor():
    """The +1PH and +2PH counters have declared their delta all along; Personal Honor becoming a
    readable stat is what lets anything ask."""
    game = two_seat_game()
    hero = put_in_play(game, personality("hero"))
    hero.adjust_counter("plus2ph", 1)

    assert effective_personal_honor(game, hero) == 2
