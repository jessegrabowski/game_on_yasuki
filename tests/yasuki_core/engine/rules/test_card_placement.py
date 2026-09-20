import datetime

import yaml

from yasuki_core import ruleset

from hooks.card_layout import scoped_registrations
from tests.yasuki_core.engine.rules.card_modules import card_modules, first_printing_module


def _belongs_in(card_id: str, scope: str | None) -> str | None:
    """The module stem a registration belongs in: the card's first printing overall, or, for one
    made under a ruleset, its first printing among that ruleset's arcs."""
    arcs = None if scope is None else getattr(ruleset, scope).arcs
    return first_printing_module(arcs=arcs).get(card_id)


def test_every_card_is_implemented_in_its_first_printing_module():
    # A reprint is implemented once. Without this, a card printed in five sets could be implemented
    # in any of them, or, worse, in two, and the module layout would stop mirroring the card data.
    misplaced = [
        f"{card_id} ({scope or 'every ruleset'}) is in {module.stem}.py "
        f"but belongs in {_belongs_in(card_id, scope)}"
        for module in card_modules()
        for card_id, scope in sorted(set(scoped_registrations(module)), key=str)
        if _belongs_in(card_id, scope) != module.stem
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


def test_a_registration_under_a_ruleset_is_placed_within_that_rulesets_arcs(tmp_path):
    # Ring of Air is one id across two dozen printings whose text changed between arcs. Its
    # Shattered Empire ability belongs beside the printing that arc played, not the 1995 one.
    for stem, titles in [("old_set", ["Ring of Air"]), ("new_set", ["Ring of Air"])]:
        cards = "".join(f"  - title: {title}\n" for title in titles)
        (tmp_path / f"{stem}.yaml").write_text(f"set: {stem}\ncards:\n{cards}")
    set_info = tmp_path / "set_info.yaml"
    set_info.write_text(
        yaml.safe_dump(
            {
                "arcs": [
                    {
                        "name": "Old",
                        "sets": [
                            {"set_name": "old_set", "release_date": datetime.date(1995, 8, 1)}
                        ],
                    },
                    {
                        "name": "New",
                        "sets": [
                            {"set_name": "new_set", "release_date": datetime.date(2016, 1, 1)}
                        ],
                    },
                ]
            }
        )
    )

    assert first_printing_module(tmp_path, set_info)["ring_of_air"] == "old_set"
    assert first_printing_module(tmp_path, set_info, arcs=("New",))["ring_of_air"] == "new_set"
    assert "ring_of_air" not in first_printing_module(tmp_path, set_info, arcs=("Neither",))
