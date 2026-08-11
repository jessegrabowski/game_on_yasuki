import pytest

from numpy.random import default_rng

from yasuki_core.game_pieces.deck import Deck, FateDeck, DynastyDeck
from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import DynastyPrint, FatePrint
from yasuki_core.engine.players import PlayerId


def mk_fate(i: int) -> L5RCard:
    return L5RCard.of(FatePrint, id=f"f{i}", name=f"Fate {i}", side=Side.FATE, owner=PlayerId.P1)


def mk_dyn(i: int) -> L5RCard:
    return L5RCard.of(
        DynastyPrint, id=f"d{i}", name=f"Dyn {i}", side=Side.DYNASTY, owner=PlayerId.P1
    )


def test_generic_deck_draw_peek_add_and_len():
    cards = [mk_fate(i) for i in range(5)]
    deck = Deck.build(cards)
    assert len(deck) == 5

    top_two = deck.peek(2)
    assert [c.id for c in top_two] == ["f3", "f4"]
    assert deck.peek(0) == []

    drawn = deck.draw(3)
    assert [c.id for c in drawn] == ["f4", "f3", "f2"]
    assert len(deck) == 2

    deck.add_to_top([mk_fate(99)])
    assert deck.draw_one().id == "f99"

    deck.add_to_bottom([mk_fate(100)])
    _ = deck.draw(10)
    assert deck.draw_one() is None


def test_shuffle_is_deterministic_with_seed():
    cards = [mk_fate(i) for i in range(5)]
    d1 = Deck.build(cards)
    d2 = Deck.build(cards)
    d1.shuffle(default_rng(123))
    d2.shuffle(default_rng(123))
    assert [c.id for c in d1.cards] == [c.id for c in d2.cards]


def test_fate_and_dynasty_deck_build_validate_types():
    f_cards = [mk_fate(i) for i in range(3)]
    d_cards = [mk_dyn(i) for i in range(3)]

    FateDeck.build(f_cards)
    DynastyDeck.build(d_cards)

    with pytest.raises(ValueError):
        FateDeck.build([mk_fate(1), mk_dyn(1)])

    with pytest.raises(ValueError):
        DynastyDeck.build([mk_dyn(1), mk_fate(1)])
