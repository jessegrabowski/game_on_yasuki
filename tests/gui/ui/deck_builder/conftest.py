import pytest
from unittest.mock import patch

MOCK_FORMATS = [
    "Clan Wars (Imperial)",
    "Hidden Emperor (Jade)",
    "Four Winds (Gold)",
    "Modern",
    "Legacy",
    "Not Legal (Proxy)",
    "Unreleased",
]

MOCK_SETS = ["Set Alpha", "Set Beta", "Set Gamma", "Set Delta"]

MOCK_DECKS = ["DYNASTY", "FATE", "PRE_GAME"]

MOCK_CLANS = ["Clan A", "Clan B", "Clan C"]

MOCK_TYPES = [
    "Event",
    "Follower",
    "Holding",
    "Item",
    "Personality",
    "Spell",
    "Strategy",
    "Stronghold",
]

MOCK_RARITIES = ["Common", "Rare", "Uncommon"]

MOCK_STAT_RANGES = {
    "force": (0, 10),
    "chi": (0, 8),
    "honor_requirement": (0, 12),
    "gold_cost": (0, 10),
    "personal_honor": (0, 5),
    "province_strength": (0, 10),
    "gold_production": (0, 6),
    "starting_honor": (0, 10),
    "focus": (0, 4),
}

MOCK_STAT_TYPE_MAPPINGS = {
    "force": ({"Personality", "Follower"}, {"DYNASTY", "FATE"}),
    "chi": ({"Personality"}, {"DYNASTY"}),
    "honor_requirement": ({"Personality"}, {"DYNASTY"}),
    "gold_cost": ({"Personality", "Holding", "Follower", "Item", "Spell"}, {"DYNASTY", "FATE"}),
    "personal_honor": ({"Personality"}, {"DYNASTY"}),
    "province_strength": ({"Stronghold"}, {"PRE_GAME", "DYNASTY"}),
    "gold_production": ({"Holding", "Stronghold"}, {"DYNASTY", "PRE_GAME"}),
    "starting_honor": ({"Stronghold"}, {"PRE_GAME"}),
    "focus": ({"Follower", "Item", "Spell", "Strategy"}, {"FATE"}),
}

_PATCH_TARGET = "app.gui.ui.deck_builder.filter_dialog"


@pytest.fixture(autouse=True)
def mock_filter_dialog_db():
    with (
        patch(f"{_PATCH_TARGET}.query_all_formats", return_value=MOCK_FORMATS),
        patch(f"{_PATCH_TARGET}.query_all_sets", return_value=MOCK_SETS),
        patch(f"{_PATCH_TARGET}.query_sets_by_format", return_value=MOCK_SETS),
        patch(f"{_PATCH_TARGET}.query_all_decks", return_value=MOCK_DECKS),
        patch(f"{_PATCH_TARGET}.query_all_clans", return_value=MOCK_CLANS),
        patch(f"{_PATCH_TARGET}.query_all_types", return_value=MOCK_TYPES),
        patch(f"{_PATCH_TARGET}.query_all_rarities", return_value=MOCK_RARITIES),
        patch(f"{_PATCH_TARGET}.query_types_by_deck", return_value=MOCK_TYPES),
        patch(f"{_PATCH_TARGET}.query_cards_filtered", return_value=[]),
        patch(f"{_PATCH_TARGET}.query_stat_ranges", return_value=MOCK_STAT_RANGES),
        patch(
            f"{_PATCH_TARGET}.query_all_stat_type_mappings", return_value=MOCK_STAT_TYPE_MAPPINGS
        ),
    ):
        yield
