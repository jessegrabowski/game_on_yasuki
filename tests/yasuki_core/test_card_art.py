import datetime

from yasuki_core.card_art import (
    ART_RECTS,
    CustomPrint,
    art_rect,
    classify,
    cover_crop,
    custom_print_id,
    era_for_date,
    load_art_layout,
)


def test_layout_asset_is_loaded_and_well_formed():
    # Contract, not an exact count (the table grows as cells are measured): the asset loads and
    # every rect is a normalized, well-ordered box.
    assert len(ART_RECTS) > 40
    assert load_art_layout()["default_layout"] == "Strategy"
    for key, rect in ART_RECTS.items():
        assert len(rect) == 4, key
        left, top, right, bottom = rect
        assert all(0.0 <= v <= 1.0 for v in rect), (key, rect)
        assert left < right and top < bottom, (key, rect)


def test_era_for_date_bands():
    assert era_for_date(datetime.date(1998, 1, 1)) == "1995-99"
    assert era_for_date(datetime.date(2004, 12, 31)) == "2000-04"
    assert era_for_date(datetime.date(2006, 6, 1)) == "2005-09"
    # The Heaven's Will (2008-10) is the full-bleed boundary: just before is titled, on/after joins
    # the 2010-15 full-bleed family.
    assert era_for_date(datetime.date(2008, 5, 1)) == "2005-09"
    assert era_for_date(datetime.date(2008, 10, 1)) == "2010-15"
    assert era_for_date(datetime.date(2015, 1, 1)) == "2010-15"
    assert era_for_date(datetime.date(2023, 1, 1)) == "2016+"
    assert era_for_date(None) == "2016+"


def test_art_rect_falls_back_to_era_strategy_then_modern():
    # Missing type within a real era -> that era's Strategy window.
    assert art_rect(("2000-04", "Nonexistent")) == ART_RECTS[("2000-04", "Strategy")]
    # Unknown era entirely -> modern Strategy.
    assert art_rect(("9999", "Nonsense")) == ART_RECTS[("2016+", "Strategy")]


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args):
        pass

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return _FakeCursor(self._rows)


def test_era_for_set_falls_back_to_arc_floor(monkeypatch):
    import yasuki_core.card_art as ca

    rows = [
        {
            "set_name": "Imperial Edition",
            "release_date": datetime.date(1995, 10, 1),
            "arc": "Clan Wars",
        },
        {"set_name": "Gold Edition", "release_date": datetime.date(2001, 6, 1), "arc": "Gold"},
        {
            "set_name": "Samurai Edition",
            "release_date": datetime.date(2007, 7, 1),
            "arc": "Samurai",
        },
        {"set_name": "Death at Koten", "release_date": datetime.date(2009, 4, 1), "arc": "Samurai"},
        {"set_name": "Samurai Edition Banzai", "release_date": None, "arc": "Samurai"},
        {"set_name": "Modern Promo", "release_date": None, "arc": "Onyx"},
        {"set_name": "Onyx Edition", "release_date": datetime.date(2023, 1, 1), "arc": "Onyx"},
    ]
    monkeypatch.setattr("yasuki_core.database.get_db_connection", lambda: _FakeConn(rows))
    monkeypatch.setattr(ca, "_set_dates", None)

    assert ca.era_for_set("Samurai Edition") == "2005-09"
    # No release date -> inherits the earliest dated set in its arc (Samurai Edition, 2007-07).
    assert ca.era_for_set("Samurai Edition Banzai") == "2005-09"
    assert ca.era_for_set("Modern Promo") == "2016+"

    # Card back flips at Gold Edition (2001-06): before is the old back, Gold onward the new.
    assert ca.back_era_for_set("Imperial Edition") == "old"
    assert ca.back_era_for_set("Gold Edition") == "new"
    assert ca.back_era_for_set("Samurai Edition") == "new"


def test_classify_maps_type_to_layout_without_db(monkeypatch):
    monkeypatch.setattr("yasuki_core.card_art.era_for_set", lambda _set: "2010-15")
    assert classify({"types": ["Ancestor"]}, "Anything") == ("2010-15", "Ancestor")
    assert classify({"types": ["Item"]}, "Anything") == ("2010-15", "Item")
    assert classify({"types": ["Event"]}, "Anything") == ("2010-15", "Event")
    assert classify({"types": []}, "Anything") == ("2010-15", "Strategy")


def test_cover_crop_matches_target_aspect_and_centers():
    left, top, right, bottom = cover_crop((0, 0, 200, 100), 50, 100)
    assert (top, bottom) == (0, 100)
    assert right - left == 50
    assert left == (200 - 50) // 2

    left, top, right, bottom = cover_crop((0, 0, 100, 200), 100, 50)
    assert (left, right) == (0, 100)
    assert bottom - top == 50
    assert top == (200 - 50) // 2


def test_custom_print_id_is_stable_negative_and_recipe_specific():
    recipe = CustomPrint("collision", 100, "ikumu", 200)
    assert custom_print_id(recipe) == custom_print_id(CustomPrint("collision", 100, "ikumu", 200))
    assert custom_print_id(recipe) < 0
    assert custom_print_id(recipe) != custom_print_id(CustomPrint("collision", 100, "ikumu", 201))
