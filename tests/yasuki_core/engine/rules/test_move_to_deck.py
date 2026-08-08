import pytest

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.rules.effects import MoveToDeck
from yasuki_core.engine.rules.triggers import resolve_effects
from yasuki_core.engine.table import DeckKey
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.dynasty import DynastyCard

from tests.yasuki_core.engine.builders import province_card, two_seat_game

P1 = PlayerId.P1
DYNASTY = DeckKey(P1, Side.DYNASTY)


def _game_with_a_three_card_deck():
    """P1 holding "mover" in a Province, over a dynasty deck of bottom, middle, top."""
    game = two_seat_game()
    province_card(game, "mover", seat=P1)
    resident = [
        DynastyCard(id=name, name=name, side=Side.DYNASTY, owner=P1)
        for name in ("bottom", "middle", "top")
    ]
    game.table.cards_by_id.update({card.id: card for card in resident})
    game.table.decks[DYNASTY].cards = resident
    return game


def _order(game):
    """The deck's card ids bottom-first, which is the order the engine list itself keeps."""
    return [card.id for card in game.table.decks[DYNASTY].cards]


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        ({"from_bottom": 0}, ["mover", "bottom", "middle", "top"]),
        ({"from_top": 0}, ["bottom", "middle", "top", "mover"]),
        ({"from_top": 1}, ["bottom", "middle", "mover", "top"]),
        ({"from_top": 2}, ["bottom", "mover", "middle", "top"]),
        ({"from_bottom": 1}, ["bottom", "mover", "middle", "top"]),
        ({"from_top": 4}, ["mover", "bottom", "middle", "top"]),
        ({"from_top": 99}, ["mover", "bottom", "middle", "top"]),
        ({"from_bottom": 99}, ["bottom", "middle", "top", "mover"]),
    ],
    ids=[
        "bottom",
        "top",
        "second from top",
        "third from top",
        "second from bottom",
        "one past the bottom clamps",
        "far past the bottom clamps",
        "past the top clamps",
    ],
)
def test_a_card_lands_at_the_depth_it_was_given(kwargs, expected):
    # A depth one past the bottom is the case that needs real clamping: it translates to index -1,
    # which list.insert would read from the far end and place second from the top instead.
    game = _game_with_a_three_card_deck()

    resolve_effects(game, [MoveToDeck("mover", DYNASTY, **kwargs)])

    assert _order(game) == expected


def test_the_two_ends_name_the_same_slot_from_opposite_directions():
    # from_top and from_bottom are one coordinate read two ways, so on a deck of three the third
    # from the top and the second from the bottom have to be the same place. Testing each end
    # separately would let a translation that is off by one on one side alone pass.
    from_top = _game_with_a_three_card_deck()
    from_bottom = _game_with_a_three_card_deck()

    resolve_effects(from_top, [MoveToDeck("mover", DYNASTY, from_top=2)])
    resolve_effects(from_bottom, [MoveToDeck("mover", DYNASTY, from_bottom=1)])

    assert _order(from_top) == _order(from_bottom)


def test_a_card_already_in_the_deck_does_not_count_itself():
    # The card leaves its slot before it lands, so a depth from the top measured against the deck
    # it is still sitting in lands one card too shallow. Only from_top reads the deck's size, so a
    # from_bottom move would pass here whether or not the card counts itself.
    game = _game_with_a_three_card_deck()

    resolve_effects(game, [MoveToDeck("bottom", DYNASTY, from_top=1)])

    assert _order(game) == ["middle", "bottom", "top"]


def test_moving_cards_in_order_puts_the_last_one_at_the_very_bottom():
    # Each card sent to the bottom pushes the one before it up, so the card moved last ends up
    # under the others.
    game = _game_with_a_three_card_deck()
    province_card(game, "second", seat=P1, index=1)

    resolve_effects(
        game,
        [MoveToDeck("mover", DYNASTY, from_bottom=0), MoveToDeck("second", DYNASTY, from_bottom=0)],
    )

    assert _order(game) == ["second", "mover", "bottom", "middle", "top"]


def test_moving_a_card_that_no_longer_exists_is_a_no_op():
    game = _game_with_a_three_card_deck()

    resolve_effects(game, [MoveToDeck("ghost", DYNASTY, from_top=0)])

    assert _order(game) == ["bottom", "middle", "top"]


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"from_top": 1, "from_bottom": 1}],
    ids=["neither end", "both ends"],
)
def test_a_depth_must_name_exactly_one_end(kwargs):
    # Defaulting a forgotten argument would land the card on top silently, which is a legal
    # position and so indistinguishable from an intended one.
    with pytest.raises(ValueError, match="exactly one of from_top or from_bottom"):
        MoveToDeck("mover", DYNASTY, **kwargs)


@pytest.mark.parametrize("kwargs", [{"from_top": -1}, {"from_bottom": -2}], ids=["top", "bottom"])
def test_a_negative_depth_is_rejected(kwargs):
    # Python would read a negative index from the far end, quietly mirroring the effect's meaning.
    with pytest.raises(ValueError, match="cannot be negative"):
        MoveToDeck("mover", DYNASTY, **kwargs)
