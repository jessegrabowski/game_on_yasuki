import pytest

from yasuki_core.game_pieces.constants import Side
from yasuki_core.game_pieces.cards import L5RCard
from yasuki_core.game_pieces.prints import SenseiPrint, StrongholdPrint, WindPrint
from yasuki_core.paths import DEFAULT_STRONGHOLD, DEFAULT_SENSEI, DEFAULT_WIND


@pytest.mark.parametrize(
    "print_cls, side, expected_art",
    [
        (StrongholdPrint, Side.STRONGHOLD, DEFAULT_STRONGHOLD),
        (SenseiPrint, Side.FATE, DEFAULT_SENSEI),
        (WindPrint, Side.FATE, DEFAULT_WIND),
    ],
)
def test_each_pre_game_card_wires_its_default_art(print_cls, side, expected_art):
    assert L5RCard.of(print_cls, id="c", name="C", side=side).image_front == expected_art


def test_honor_bearing_pre_game_cards_default_to_zero_honor():
    assert L5RCard.of(StrongholdPrint, id="sh", name="S", side=Side.STRONGHOLD).starting_honor == 0
    assert L5RCard.of(SenseiPrint, id="se", name="S", side=Side.FATE).starting_honor == 0
