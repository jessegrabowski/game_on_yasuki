import datetime

import pytest

from yasuki_core.install.sets_to_sql import coerce_date
from yasuki_core.install.yaml_to_sql import (
    build_revisions,
    card_slug,
    mrp_text,
    parse_collector_numbers,
    _apply_current_revision,
    _BACK_CARD_ID_COL,
    _card_columns,
    _experience_level,
    _link_and_validate_back_faces,
    _print_columns,
    _revision_baseline,
    _RULES_TEXT_COL,
    _STAT_COL,
    _validate_creates,
)

# The prints INSERT column order in yaml_to_sql._insert_all; the row tuple from _print_columns is
# positional against it, so name-index the tuple to assert intent instead of a bare magic offset.
_PRINT_COLS = [
    "card_id",
    "printing_id",
    "set_id",
    "rarity",
    "flavor_text",
    "rules_text",
    "back_title",
    "back_flavor",
    "artist",
    "designer",
    "collector_number_raw",
    "publisher",
    "publisher_url",
    "doublesided",
    "legal_date",
]


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


def test_build_revisions_puts_original_first_and_current_last():
    errata = [
        {
            "date": "2026-07-01",
            "source": "July 2026",
            "source_url": "https://example.test/errata",
            "text": "new text",
            "art": "ring__errata.jpg",
            "set_slug": "rise_of_otosan_uchi",
        },
    ]
    revisions = build_revisions("old text", errata)
    assert [r.revision_index for r in revisions] == [0, 1]
    original, current = revisions
    assert original.rules_text == "old text"
    assert (
        original.source is None and original.effective_date is None and original.image_path is None
    )
    assert original.source_url is None
    assert current.rules_text == "new text"
    assert current.source == "July 2026"
    assert current.source_url == "https://example.test/errata"
    assert current.effective_date == datetime.date(2026, 7, 1)
    assert current.image_path == "sets/rise_of_otosan_uchi/ring__errata.jpg"
    assert current.stats == {}


def test_build_revisions_sorts_errata_by_effective_date():
    errata = [
        {"date": "2026-07-01", "text": "second"},
        {"date": "2024-01-01", "text": "first"},
    ]
    revisions = build_revisions("orig", errata)
    assert [r.rules_text for r in revisions] == ["orig", "first", "second"]
    assert [r.revision_index for r in revisions] == [0, 1, 2]


def test_build_revisions_rejects_unparseable_date():
    with pytest.raises(ValueError, match="unparseable date"):
        build_revisions("orig", [{"date": "2026-13-05", "text": "bad month"}])


def test_build_revisions_rejects_missing_date():
    with pytest.raises(ValueError, match="unparseable date"):
        build_revisions("orig", [{"text": "no date at all"}])


def test_build_revisions_captures_only_integer_stat_overrides():
    errata = [{"date": "2026-07-01", "text": "t", "force": 5, "chi": 3, "gold_cost": "+2"}]
    revision = build_revisions("orig", errata)[-1]
    assert revision.stats == {"force": 5, "chi": 3}  # the non-integer "+2" is not a stat override
    assert revision.image_path is None  # no art on this erratum


def test_revision_baseline_uses_oldest_erratum_home_text():
    # The oldest erratum's home printing supplies rev 0, even when a later erratum came from elsewhere.
    errata = [
        {"date": "2026-07-01", "home_text": "shattered empire text"},
        {"date": "2024-01-01", "home_text": "pre-errata printed text"},
    ]
    assert _revision_baseline(errata, "first-seen fallback") == "pre-errata printed text"


def test_revision_baseline_falls_back_when_home_text_absent():
    assert (
        _revision_baseline([{"date": "2026-07-01"}], "first-seen fallback") == "first-seen fallback"
    )


def test_apply_current_revision_overrides_text_and_accumulates_stats():
    row, _ = _card_columns("x", "X", {"title": "X", "force": 2, "chi": 2})
    errata = [
        {"date": "2024-01-01", "text": "mid", "force": 4},
        {"date": "2026-07-01", "text": "current", "chi": 5},
    ]
    _apply_current_revision(row, build_revisions("orig", errata))
    assert row[_RULES_TEXT_COL] == "current"
    assert row[_STAT_COL["force"]] == 4  # set by the earlier erratum, unchanged by the later one
    assert row[_STAT_COL["chi"]] == 5  # overridden by the later erratum


def test_mrp_text_picks_the_newest_printing():
    dated = [
        (datetime.date(1998, 1, 1), "samurai edition text"),
        (datetime.date(2025, 2, 1), "shattered empire text"),
        (datetime.date(2023, 1, 1), "onyx edition text"),
    ]
    assert mrp_text(dated) == "shattered empire text"


def test_mrp_text_treats_null_date_as_oldest():
    dated = [(None, "undated printing"), (datetime.date(2014, 6, 9), "dated printing")]
    assert mrp_text(dated) == "dated printing"


def test_mrp_text_returns_none_for_no_printings():
    assert mrp_text([]) is None


def test_print_columns_maps_print_text_to_rules_text_slot():
    entry = {
        "print_text": "reworded on this printing",
        "flavor_text": "flavor",
        "rarity": "Uncommon",
    }
    row = dict(zip(_PRINT_COLS, _print_columns(entry, "cid", "some_set", 7)))
    assert row["rules_text"] == "reworded on this printing"
    assert row["flavor_text"] == "flavor"  # the printing's own text does not clobber flavor
    assert (row["card_id"], row["printing_id"], row["set_id"]) == ("cid", "some_set", 7)


def test_print_columns_absent_print_text_is_null():
    # No print_text ⇒ NULL, so readers fall back to the card's canonical (MRP + errata) text. The
    # card's own `text` field must not leak onto the printing.
    row = dict(zip(_PRINT_COLS, _print_columns({"text": "card canonical"}, "cid", "some_set", 7)))
    assert row["rules_text"] is None


def test_creates_edges_with_known_endpoints_pass():
    cards = {"akodo_kage": None, "token_plus1f": None}
    _validate_creates(cards, {("akodo_kage", "token_plus1f")})


def test_creates_edge_with_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown card ids"):
        _validate_creates({"akodo_kage": None}, {("akodo_kage", "token_ghost")})


def test_self_referential_create_raises():
    with pytest.raises(ValueError, match="self-referential"):
        _validate_creates({"akodo_kage": None}, {("akodo_kage", "akodo_kage")})
