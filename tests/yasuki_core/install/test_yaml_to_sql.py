import datetime

import pytest

from yasuki_core.install.sets_to_sql import coerce_date
from yasuki_core.install.yaml_to_sql import (
    card_slug,
    parse_collector_numbers,
    _BACK_CARD_ID_COL,
    _card_columns,
    _experience_level,
    _link_and_validate_back_faces,
)


@pytest.mark.parametrize(
    "extended_title, expected",
    [
        ("Bayushi Kachiko", 0),
        ("Bayushi Kachiko • Inexperienced", -1),
        ("Bayushi Kachiko • Experienced", 1),
        ("Bayushi Kachiko • ExperiencedCoM", 1),
        ("Bayushi Kachiko • Experienced 2", 2),
        ("Bayushi Kachiko, Seven Thunder • Experienced 2CW", 2),
        ("Hantei Kachiko • Experienced 3KYD", 3),
    ],
)
def test_experience_level(extended_title, expected):
    assert _experience_level(extended_title) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2012-11-05", datetime.date(2012, 11, 5)),
        ("November 5th, 2012", datetime.date(2012, 11, 5)),
        ("May 23rd, 1999", datetime.date(1999, 5, 23)),
        ("November 1st, 2010", datetime.date(2010, 11, 1)),
        ("Upon Release", None),
        ("-", None),
        ("", None),
        (None, None),
    ],
)
def test_coerce_date(raw, expected):
    assert coerce_date(raw) == expected


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


def _row(card_id, title, is_back=False):
    row, _ = _card_columns(card_id, title, {"title": title, "is_back": is_back})
    return row


def test_back_face_links_to_its_front():
    cards = {
        "dark_capital": _row("dark_capital", "The Dark Capital"),
        "dark_capital__back": _row("dark_capital__back", "The Dark Capital", is_back=True),
    }
    names = {"dark_capital": "The Dark Capital", "dark_capital__back": "The Dark Capital"}
    _link_and_validate_back_faces(cards, names, {"dark_capital__back"})
    assert cards["dark_capital"][_BACK_CARD_ID_COL] == "dark_capital__back"


def test_back_face_without_matching_front_raises():
    cards = {"orphan__back": _row("orphan__back", "Orphan", is_back=True)}
    with pytest.raises(ValueError, match="no front"):
        _link_and_validate_back_faces(cards, {"orphan__back": "Orphan"}, {"orphan__back"})
