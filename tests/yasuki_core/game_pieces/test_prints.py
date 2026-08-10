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


def test_borrowed_art_is_not_part_of_a_prints_identity():
    """Two copies of a card differ only in whose art they wear, and replay compares a rebuilt game
    to the original by value — so the swap payload has to stay out of equality the way it does on
    the card."""
    made = dict(name="Farm", side=Side.DYNASTY, printed_id="modest_farm", gold_production=1)

    assert HoldingPrint(**made, art_swap={"donor_img": "a.png"}) == HoldingPrint(**made)
    assert HoldingPrint(**made) != HoldingPrint(**{**made, "gold_production": 2})
