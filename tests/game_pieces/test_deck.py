from app.game_pieces.deck import Deck, FateDeck, DynastyDeck
from app.game_pieces.fate import FateCard
from app.game_pieces.dynasty import DynastyCard
from app.game_pieces.constants import Side


def mk_fate(i: int) -> FateCard:
    return FateCard(id=f"f{i}", name=f"Fate {i}", side=Side.FATE)


def mk_dyn(i: int) -> DynastyCard:
    return DynastyCard(id=f"d{i}", name=f"Dyn {i}", side=Side.DYNASTY)


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
    d1.shuffle(seed=123)
    d2.shuffle(seed=123)
    assert [c.id for c in d1.cards] == [c.id for c in d2.cards]


def test_fate_and_dynasty_deck_build_validate_types():
    f_cards = [mk_fate(i) for i in range(3)]
    d_cards = [mk_dyn(i) for i in range(3)]

    FateDeck.build(f_cards)
    DynastyDeck.build(d_cards)

    try:
        FateDeck.build([mk_fate(1), mk_dyn(1)])
    except ValueError:
        pass
    else:
        raise AssertionError("FateDeck.build should reject non-FateCard instances")

    try:
        DynastyDeck.build([mk_dyn(1), mk_fate(1)])
    except ValueError:
        pass
    else:
        raise AssertionError("DynastyDeck.build should reject non-DynastyCard instances")
