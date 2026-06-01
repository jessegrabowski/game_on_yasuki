from pathlib import Path

import pytest
from PIL import Image

from yasuki_core.card_art import CustomPrint, custom_print_id, overlays_for
from yasuki_gui.ui.deck_builder.custom_art import (
    composite_art,
    custom_print_record,
    render_custom_image,
)

RECIPIENT = Path("sets/rise_of_jigoku/a_collision_of_wills.jpg")
DONOR = Path("sets/a_perfect_cut/a_desperate_act.jpg")
HOLDING = Path("sets/chaos_reigns_part_ii/millet_farm.jpg")

_needs_images = pytest.mark.skipif(
    not (RECIPIENT.exists() and DONOR.exists()), reason="card images not present locally"
)
_needs_holding = pytest.mark.skipif(
    not (HOLDING.exists() and DONOR.exists()), reason="card images not present locally"
)


def test_custom_print_record_shape_and_donor_label():
    class Repo:
        def get_card(self, card_id):
            return {"card_id": "ikumu", "name": "Togashi Ikumu", "extended_title": "Togashi Ikumu"}

    recipe = CustomPrint("collision", 100, "ikumu", 200)
    record = custom_print_record(recipe, Repo())
    assert record["print_id"] == custom_print_id(recipe)
    assert record["card_id"] == "collision"
    assert record["is_custom"] is True
    assert record["recipe"] is recipe
    assert record["image_path"] is None
    assert "Togashi Ikumu" in record["set_name"]


def test_render_custom_image_returns_none_when_card_or_print_missing():
    class Repo:
        def __init__(self, cards, prints):
            self._cards, self._prints = cards, prints

        def get_card(self, card_id):
            return self._cards.get(card_id)

        def get_prints(self, card_id):
            return self._prints.get(card_id, [])

    recipe = CustomPrint("rec", 1, "don", 2)
    assert render_custom_image(recipe, Repo({"rec": {"card_id": "rec"}}, {})) is None
    both_cards = {"rec": {"card_id": "rec"}, "don": {"card_id": "don"}}
    assert render_custom_image(recipe, Repo(both_cards, {})) is None


@_needs_images
def test_composite_changes_only_the_art_window():
    out = composite_art(RECIPIENT, DONOR, ("2016+", "Strategy"), ("2000-04", "Strategy"))
    recipient = Image.open(RECIPIENT).convert("RGB")
    assert out.size == recipient.size
    # The art landed (image changed)...
    assert out.tobytes() != recipient.tobytes()
    # ...but the frame outside the window is untouched (top-left corner is left of the window).
    assert out.crop((0, 0, 5, 5)).tobytes() == recipient.crop((0, 0, 5, 5)).tobytes()


@_needs_images
def test_donor_layout_changes_crop():
    assert (
        composite_art(RECIPIENT, DONOR, ("2016+", "Strategy"), ("2000-04", "Strategy")).tobytes()
        != composite_art(
            RECIPIENT, DONOR, ("2016+", "Strategy"), ("2000-04", "Personality")
        ).tobytes()
    )


def test_overlays_for_modern_holding_only():
    overlays = overlays_for(("2016+", "Holding"))
    assert len(overlays) == 1
    assert overlays[0]["asset"] == "holding_flair.png"
    assert overlays_for(("2016+", "Personality")) == []


@_needs_holding
def test_holding_swap_stamps_the_flair_over_the_art(monkeypatch):
    keys = (("2016+", "Holding"), ("2000-04", "Strategy"))
    with_flair = composite_art(HOLDING, DONOR, *keys)
    monkeypatch.setattr("yasuki_gui.ui.deck_builder.custom_art.overlays_for", lambda key: [])
    without_flair = composite_art(HOLDING, DONOR, *keys)
    assert with_flair.tobytes() != without_flair.tobytes()


@_needs_holding
def test_holding_coin_shows_through_the_flair_hole():
    out = composite_art(HOLDING, DONOR, ("2016+", "Holding"), ("2000-04", "Strategy"))
    recipient = Image.open(HOLDING).convert("RGB")
    w, h = recipient.size
    coin_center = (round(0.503 * w), round(0.564 * h))
    assert out.getpixel(coin_center) == recipient.getpixel(coin_center)
