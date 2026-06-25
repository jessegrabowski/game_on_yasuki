import pytest

from yasuki_core.game_pieces.pregame import StrongholdCard, SenseiCard, WindCard
from yasuki_core.game_pieces.constants import Side
from yasuki_core.paths import DEFAULT_STRONGHOLD, DEFAULT_SENSEI, DEFAULT_WIND


@pytest.mark.parametrize(
    "card_cls, side, expected_art",
    [
        (StrongholdCard, Side.STRONGHOLD, DEFAULT_STRONGHOLD),
        (SenseiCard, Side.FATE, DEFAULT_SENSEI),
        (WindCard, Side.FATE, DEFAULT_WIND),
    ],
)
def test_each_pre_game_card_wires_its_default_art(card_cls, side, expected_art):
    assert card_cls(id="c", name="C", side=side).image_front == expected_art


def test_honor_bearing_pre_game_cards_default_to_zero_honor():
    assert StrongholdCard(id="sh", name="S", side=Side.STRONGHOLD).starting_honor == 0
    assert SenseiCard(id="se", name="S", side=Side.FATE).starting_honor == 0
