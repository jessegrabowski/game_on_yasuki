import pytest

from yasuki_core.engine import ops
from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    BATTLEFIELD,
    BoardPos,
    Location,
    TableState,
    ZoneKey,
    ZoneRole,
    location_of,
)
from yasuki_core.game_pieces.constants import AttachmentType

from tests.yasuki_core.engine.builders import attached, attachment, personality, put_in_play


def test_a_home_names_a_seat_and_no_battlefield():
    home = Location.home(PlayerId.P1)

    assert home.is_home
    assert home.seat is PlayerId.P1
    assert home.battlefield is None
    assert home.is_well_formed()


def test_a_battlefield_names_an_index_and_no_seat():
    field = Location.at_battlefield(2)

    assert not field.is_home
    assert field.battlefield == 2
    assert field.seat is None
    assert field.is_well_formed()


@pytest.mark.parametrize(
    "location",
    [Location(), Location(seat=PlayerId.P1, battlefield=0)],
    ids=["neither", "both"],
)
def test_a_location_naming_neither_or_both_is_malformed(location):
    assert not location.is_well_formed()


def test_a_card_with_no_entry_is_at_its_owners_home():
    state = TableState.empty_two_seat()
    theirs = put_in_play(state, personality("p2-hero", owner=PlayerId.P2))

    assert state.locations == {}
    assert location_of(state, theirs) == Location.home(PlayerId.P2)


def test_a_recorded_location_wins_over_the_default():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))
    state.locations[hero.id] = Location.at_battlefield(1)

    assert location_of(state, hero) == Location.at_battlefield(1)


def _unit_at_home(state: TableState, *, owner: PlayerId = PlayerId.P1):
    """A Personality with a Follower and an Item attached, in play at its owner's home."""
    hero = put_in_play(state, personality("hero", owner=owner))
    ashigaru = attached(
        state,
        attachment("ashigaru", owner=owner, attachment_type=AttachmentType.FOLLOWER),
        hero.id,
    )
    blade = attached(
        state, attachment("blade", owner=owner, attachment_type=AttachmentType.ITEM), hero.id
    )
    return hero, ashigaru, blade


def test_set_location_stores_a_battlefield_and_reports_the_move():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))

    assert ops.set_location(state, hero, Location.at_battlefield(0))
    assert state.locations == {hero.id: Location.at_battlefield(0)}
    assert not ops.set_location(state, hero, Location.at_battlefield(0))


def test_set_location_stores_the_owners_home_as_no_entry():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero", owner=PlayerId.P1))
    ops.set_location(state, hero, Location.at_battlefield(0))

    assert ops.set_location(state, hero, Location.home(PlayerId.P1))
    assert state.locations == {}
    assert location_of(state, hero) == Location.home(PlayerId.P1)


def test_set_location_reports_no_move_for_a_card_already_at_its_own_home():
    """The one case where both the recorded location and the requested one are the implicit default,
    so the answer cannot come from comparing dict entries."""
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero", owner=PlayerId.P1))

    assert not ops.set_location(state, hero, Location.home(PlayerId.P1))
    assert state.locations == {}


def test_set_location_stores_the_other_seats_home():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero", owner=PlayerId.P1))

    assert ops.set_location(state, hero, Location.home(PlayerId.P2))
    assert state.locations == {hero.id: Location.home(PlayerId.P2)}


def test_set_location_refuses_a_malformed_location():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))

    with pytest.raises(ValueError, match="names neither a home nor a battlefield"):
        ops.set_location(state, hero, Location())


def test_assign_moves_the_whole_unit():
    state = TableState.empty_two_seat()
    hero, ashigaru, blade = _unit_at_home(state)

    assert ops.assign(state, hero, 1)

    for card in (hero, ashigaru, blade):
        assert location_of(state, card) == Location.at_battlefield(1)
    state.validate()


def test_assign_leaves_another_unit_at_home():
    state = TableState.empty_two_seat()
    hero, _, _ = _unit_at_home(state)
    bystander = put_in_play(state, personality("bystander"))

    ops.assign(state, hero, 0)

    assert location_of(state, bystander) == Location.home(PlayerId.P1)


def test_return_home_takes_the_whole_unit_back():
    state = TableState.empty_two_seat()
    hero, ashigaru, blade = _unit_at_home(state)
    ops.assign(state, hero, 0)

    assert ops.return_home(state, hero)

    assert state.locations == {}
    for card in (hero, ashigaru, blade):
        assert location_of(state, card) == Location.home(PlayerId.P1)


def test_return_home_reports_no_move_for_a_unit_already_home():
    state = TableState.empty_two_seat()
    hero, _, _ = _unit_at_home(state)

    assert not ops.return_home(state, hero)


def test_a_unit_returns_to_its_personalitys_home_not_each_owners():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero", owner=PlayerId.P1))
    gift = attached(
        state,
        attachment("gift", owner=PlayerId.P2, attachment_type=AttachmentType.FOLLOWER),
        hero.id,
    )
    ops.assign(state, hero, 0)

    ops.return_home(state, hero)

    assert location_of(state, gift) == Location.home(PlayerId.P1)


def test_assigning_a_lone_card_is_a_unit_of_one():
    state = TableState.empty_two_seat()
    solo = put_in_play(state, personality("solo"))

    assert ops.assign(state, solo, 2)
    assert location_of(state, solo) == Location.at_battlefield(2)


def test_a_card_leaving_play_drops_its_location():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))
    ops.assign(state, hero, 0)

    ops.move_card(state, hero, ZoneKey(PlayerId.P1, ZoneRole.DYNASTY_DISCARD))

    assert state.locations == {}
    state.validate()


def test_removing_a_card_from_the_table_drops_its_location():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))
    ops.assign(state, hero, 0)

    ops.remove_card(state, hero)

    assert state.locations == {}


def test_repositioning_on_the_table_keeps_a_battlefield_assignment():
    state = TableState.empty_two_seat()
    hero = put_in_play(state, personality("hero"))
    ops.assign(state, hero, 3)

    ops.move_card(state, hero, BATTLEFIELD, position=BoardPos(5.0, 6.0))

    assert location_of(state, hero) == Location.at_battlefield(3)
    assert state.positions[hero.id] == BoardPos(5.0, 6.0)


def test_a_card_entering_play_lands_at_its_owners_home():
    state = TableState.empty_two_seat()
    hand = ZoneKey(PlayerId.P2, ZoneRole.HAND)
    card = personality("recruit", owner=PlayerId.P2)
    state.cards_by_id[card.id] = card
    state.zones[hand].add(card)

    ops.move_card(state, card, BATTLEFIELD)

    assert state.locations == {}
    assert location_of(state, card) == Location.home(PlayerId.P2)
