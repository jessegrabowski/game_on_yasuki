import datetime

import pytest
import yaml

from tests.yasuki_core.engine.rules.card_modules import (
    card_modules,
    first_printing_module,
    registered_ids,
)


@pytest.mark.slow
def test_every_card_is_implemented_in_its_first_printing_module():
    # A reprint is implemented once. Without this, a card printed in five sets could be implemented
    # in any of them — or, worse, in two — and the module layout would stop mirroring the card data.
    # Deriving the answer costs the eight-second YAML parse, hence the marker.
    belongs = first_printing_module()
    misplaced = [
        f"{card_id} is in {module.stem}.py but first appeared in {belongs[card_id]}"
        for module in card_modules()
        for card_id in sorted(set(registered_ids(module)))
        if belongs[card_id] != module.stem
    ]

    assert misplaced == []


def write_sets(tmp_path, sets):
    """Write a set YAML per entry plus the set_info that dates them, and return both paths."""
    for stem, set_name, _, titles in sets:
        cards = "".join(f"  - title: {title}\n" for title in titles)
        (tmp_path / f"{stem}.yaml").write_text(f"set: {set_name}\ncards:\n{cards}")
    dated = [{"set_name": set_name, "release_date": release} for _, set_name, release, _ in sets]
    set_info = tmp_path / "set_info.yaml"
    set_info.write_text(yaml.safe_dump({"arcs": [{"sets": dated}]}))
    return set_info


def test_an_undated_set_still_places_its_cards(tmp_path):
    # Four sets carry no release_date, and moto_traders is printed only in one of them. Sorting
    # undated last keeps it placeable rather than leaving it with no module.
    set_info = write_sets(
        tmp_path,
        [
            ("dated", "Dated Set", datetime.date(2000, 1, 1), ["Modest Farm"]),
            ("undated", "Undated Set", None, ["Modest Farm", "Orphan Card"]),
        ],
    )

    belongs = first_printing_module(tmp_path, set_info)

    assert belongs["modest_farm"] == "dated"
    assert belongs["orphan_card"] == "undated"


def test_two_sets_sharing_a_release_date_break_on_file_stem(tmp_path):
    # Release dates are month-granular across 130 sets, so ties happen. Breaking on the file stem
    # keeps the answer identical on every machine rather than depending on directory order.
    same_day = datetime.date(1995, 8, 1)
    set_info = write_sets(
        tmp_path,
        [
            ("zebra_set", "Zebra Set", same_day, ["Modest Farm"]),
            ("alpha_set", "Alpha Set", same_day, ["Modest Farm"]),
        ],
    )

    assert first_printing_module(tmp_path, set_info)["modest_farm"] == "alpha_set"
