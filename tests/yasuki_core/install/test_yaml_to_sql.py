import pytest

from yasuki_core.install.yaml_to_sql import card_slug, parse_collector_numbers, _card_columns


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Refugees", "refugees"),
        ("Bayushi Kachiko • Experienced", "bayushi_kachiko_experienced"),
        ("Crimson & Jade", "crimson_and_jade"),
        ("Akodo's Grave", "akodos_grave"),
        ("A Good Day to Die", "a_good_day_to_die"),
    ],
)
def test_card_slug(title, expected):
    assert card_slug(title) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, []),
        ("", []),
        ("109", [(None, 109)]),
        ("Lion 41", [("Lion", 41)]),
        ("286, 488", [(None, 286), (None, 488)]),
        ("no-number-here", []),
    ],
)
def test_parse_collector_numbers(raw, expected):
    assert parse_collector_numbers(raw) == expected


def test_integer_stats_fill_columns_not_extra():
    _, extra = _card_columns(
        "refugees", "Refugees", {"title": "Refugees", "gold_cost": 0, "focus": 2}
    )
    assert extra == {}


def test_non_integer_stats_go_to_extra():
    _, extra = _card_columns("x", "X", {"title": "X", "force": "+2", "chi": "*"})
    assert extra == {"force_raw": "+2", "chi_raw": "*"}
