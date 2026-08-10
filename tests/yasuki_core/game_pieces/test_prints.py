from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.prints import CardPrint, FatePrint, HoldingPrint
from yasuki_core.paths import DEFAULT_HOLDING, DYNASTY_BACK, FATE_BACK


def test_a_print_carries_the_default_art_of_its_type():
    """The record supplies a card's own art; the type supplies what to draw when it has none and
    what its deck back looks like. Both live here because they are the same for every copy."""
    holding = HoldingPrint(name="Farm", side=Side.DYNASTY)
    strategy = FatePrint(name="Ambush", side=Side.FATE)

    assert (holding.image_front, holding.image_back) == (DEFAULT_HOLDING, DYNASTY_BACK)
    assert strategy.image_back == FATE_BACK


def test_a_print_normalizes_its_collections():
    printed = CardPrint(name="X", side=Side.DYNASTY, clans=["crab"], keywords=["Farm"])

    assert printed.clans == ("crab",) and printed.keywords == ("Farm",)


def test_two_prints_of_the_same_card_compare_equal():
    """Copies share one print object, but a rebuilt table compares by value — replay asserts the
    game it replayed equals the original, and the print is part of every card in it."""
    made = dict(name="Farm", side=Side.DYNASTY, printed_id="modest_farm", gold_production=1)

    assert HoldingPrint(**made) == HoldingPrint(**made)
