import pytest

from yasuki_gui.ui.deck_builder.deck_data import DeckState
from yasuki_gui.ui.deck_builder.deck_io import (
    serialize_deck,
    parse_deck_yaml,
    import_deck_yaml,
)

CARDS = {
    "kuni_yori": {
        "id": "kuni_yori",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori",
        "type": "Personality",
        "side": "DYNASTY",
    },
    "kuni_yori_exp": {
        "id": "kuni_yori_exp",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori \u2022 Experienced",
        "type": "Personality",
        "side": "DYNASTY",
    },
    "ambush": {
        "id": "ambush",
        "name": "Ambush",
        "extended_title": "Ambush",
        "type": "Strategy",
        "side": "FATE",
    },
    "kyuden_hida": {
        "id": "kyuden_hida",
        "name": "Kyuden Hida",
        "extended_title": "Kyuden Hida",
        "type": "Stronghold",
        "side": "STRONGHOLD",
    },
    "700_soldier_plain": {
        "id": "700_soldier_plain",
        "name": "700 Soldier Plain",
        "extended_title": "700 Soldier Plain",
        "type": "Holding",
        "side": "DYNASTY",
    },
}

PRINTS = {
    "kuni_yori": [
        {"print_id": 1, "set_name": "Imperial Edition"},
        {"print_id": 2, "set_name": "Pearl Edition"},
    ],
    "kuni_yori_exp": [
        {"print_id": 3, "set_name": "Pearl Edition"},
        {"print_id": 4, "set_name": "Jade Edition"},
    ],
    "ambush": [
        {"print_id": 10, "set_name": "Imperial Edition"},
        {"print_id": 11, "set_name": "Lotus Edition"},
        {"print_id": 12, "set_name": "Diamond Edition"},
    ],
    "kyuden_hida": [
        {"print_id": 20, "set_name": "Gold Edition"},
    ],
    "700_soldier_plain": [
        {"print_id": 30, "set_name": "Diamond Edition"},
    ],
}


class MockRepository:
    def __init__(self, cards=None, prints=None):
        self._cards = cards or CARDS
        self._prints = prints or PRINTS

    @property
    def cards_by_id(self):
        return self._cards

    def get_card(self, card_id):
        return self._cards.get(card_id)

    def get_prints(self, card_id):
        return self._prints.get(card_id, [])


@pytest.fixture
def repo():
    return MockRepository()


class TestParseDeckYaml:
    def test_parses_deck_name(self):
        assert parse_deck_yaml("name: My Crane Deck")["name"] == "My Crane Deck"

    def test_strips_quotes_from_name(self):
        assert parse_deck_yaml('name: "Deck: The Return"')["name"] == "Deck: The Return"

    def test_defaults_name_when_missing(self):
        assert parse_deck_yaml("fate:\n  - Ambush")["name"] == "Imported Deck"

    def test_parses_count_prefix(self):
        r = parse_deck_yaml("name: T\ndynasty:\n  - 3x Kuni Yori")
        assert r["dynasty"][0]["count"] == 3
        assert r["dynasty"][0]["name"] == "Kuni Yori"

    def test_parses_unicode_count_prefix(self):
        r = parse_deck_yaml("name: T\nfate:\n  - 2\u00d7 Ambush")
        assert r["fate"][0]["count"] == 2

    def test_parses_set_suffix(self):
        r = parse_deck_yaml("name: T\nfate:\n  - Ambush [Imperial Edition]")
        assert r["fate"][0]["set_name"] == "Imperial Edition"

    def test_does_not_confuse_numeric_card_name(self):
        r = parse_deck_yaml("name: T\ndynasty:\n  - 700 Soldier Plain")
        assert r["dynasty"][0]["name"] == "700 Soldier Plain"
        assert r["dynasty"][0]["count"] == 1

    def test_parses_bullet_character_name(self):
        r = parse_deck_yaml("name: T\ndynasty:\n  - Kuni Yori \u2022 Experienced [Pearl Edition]")
        assert r["dynasty"][0]["name"] == "Kuni Yori \u2022 Experienced"
        assert r["dynasty"][0]["set_name"] == "Pearl Edition"

    def test_ignores_comments_and_blanks(self):
        r = parse_deck_yaml("name: T\n# comment\n\nfate:\n  - Ambush\n\n")
        assert len(r["fate"]) == 1

    def test_ignores_unknown_sections(self):
        r = parse_deck_yaml("name: T\nsideboard:\n  - Ambush\nfate:\n  - Kuni Yori")
        assert len(r["fate"]) == 1
        assert r["fate"][0]["name"] == "Kuni Yori"
        assert r["dynasty"] == []

    def test_card_name_with_leading_dash_preserved(self):
        r = parse_deck_yaml("name: T\nfate:\n  - --Ranged Attack--")
        assert r["fate"][0]["name"] == "--Ranged Attack--"


class TestSerializeDeck:
    def test_includes_deck_name(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Test Deck")
        assert "name: Test Deck" in yaml

    def test_quotes_name_with_colon(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Deck: Return")
        assert '"Deck: Return"' in yaml

    def test_empty_deck_is_name_only(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Empty")
        assert yaml == "name: Empty\n"

    def test_empty_name_still_serializes(self, repo):
        yaml = serialize_deck(DeckState(), repo)
        assert yaml.startswith("name:")

    def test_omits_empty_sections(self, repo):
        state = DeckState().add_card("ambush", 10)
        yaml = serialize_deck(state, repo)
        assert "fate:" in yaml
        assert "dynasty:" not in yaml
        assert "pre_game:" not in yaml

    def test_includes_count_prefix_for_multiples(self, repo):
        state = DeckState().add_card("ambush", 10).add_card("ambush", 10)
        yaml = serialize_deck(state, repo)
        assert "2x Ambush" in yaml

    def test_setup_cards_in_pre_game_section(self, repo):
        state = DeckState().add_card("kyuden_hida", 20)
        yaml = serialize_deck(state, repo)
        assert "pre_game:" in yaml
        assert "Kyuden Hida" in yaml

    def test_skips_unknown_card_ids(self, repo):
        state = DeckState().add_card("nonexistent_card", 99).add_card("ambush", 10)
        yaml = serialize_deck(state, repo)
        assert "nonexistent" not in yaml
        assert "Ambush" in yaml

    def test_round_trip_preserves_structure(self, repo):
        state = (
            DeckState()
            .add_card("kuni_yori", 1)
            .add_card("kuni_yori", 2)
            .add_card("ambush", 10)
            .add_card("kyuden_hida", 20)
        )
        yaml = serialize_deck(state, repo, deck_name="Round Trip")
        parsed = parse_deck_yaml(yaml)
        assert parsed["name"] == "Round Trip"
        assert len(parsed["dynasty"]) == 2
        assert len(parsed["fate"]) == 1
        assert len(parsed["pre_game"]) == 1

    def test_multi_print_round_trip(self, repo):
        state = DeckState().add_card("ambush", 10).add_card("ambush", 11).add_card("ambush", 11)
        yaml = serialize_deck(state, repo, deck_name="Multi-Print")
        parsed = parse_deck_yaml(yaml)
        assert len(parsed["fate"]) == 2
        imperial = next(e for e in parsed["fate"] if e["set_name"] == "Imperial Edition")
        lotus = next(e for e in parsed["fate"] if e["set_name"] == "Lotus Edition")
        assert imperial["count"] == 1
        assert lotus["count"] == 2


class TestImportDeckYaml:
    def test_imports_simple_deck(self, repo):
        yaml = "name: Test\nfate:\n  - Ambush [Imperial Edition]"
        state, name, unresolved = import_deck_yaml(yaml, repo)
        assert name == "Test"
        assert unresolved == []
        assert "ambush" in state.cards
        assert state.cards["ambush"] == [(10, 1)]

    def test_imports_with_count(self, repo):
        yaml = "name: T\nfate:\n  - 3x Ambush [Lotus Edition]"
        state, _, _ = import_deck_yaml(yaml, repo)
        assert state.cards["ambush"] == [(11, 3)]

    def test_imports_multiple_prints_of_same_card(self, repo):
        yaml = "name: T\nfate:\n  - Ambush [Imperial Edition]\n  - 2x Ambush [Lotus Edition]"
        state, _, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        prints = state.cards["ambush"]
        assert (10, 1) in prints
        assert (11, 2) in prints

    def test_imports_setup_cards(self, repo):
        yaml = "name: T\npre_game:\n  - Kyuden Hida [Gold Edition]"
        state, _, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert "kyuden_hida" in state.cards

    def test_distinguishes_base_from_experienced(self, repo):
        yaml = (
            "name: T\ndynasty:\n"
            "  - Kuni Yori [Imperial Edition]\n"
            "  - Kuni Yori \u2022 Experienced [Pearl Edition]"
        )
        state, _, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert "kuni_yori" in state.cards
        assert "kuni_yori_exp" in state.cards

    def test_unresolved_names_reported(self, repo):
        yaml = "name: T\nfate:\n  - Nonexistent Card"
        state, _, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == ["Nonexistent Card"]
        assert state.cards == {}

    def test_falls_back_to_first_print_without_set(self, repo):
        yaml = "name: T\nfate:\n  - Ambush"
        state, _, _ = import_deck_yaml(yaml, repo)
        assert state.cards["ambush"] == [(10, 1)]

    def test_mismatched_set_falls_back_to_first_print(self, repo):
        yaml = "name: T\nfate:\n  - Ambush [Nonexistent Set]"
        state, _, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert state.cards["ambush"] == [(10, 1)]

    def test_import_empty_input(self, repo):
        state, name, unresolved = import_deck_yaml("", repo)
        assert state.cards == {}
        assert unresolved == []
        assert name == "Imported Deck"

    def test_full_round_trip(self, repo):
        original = (
            DeckState()
            .add_card("kuni_yori", 1)
            .add_card("kuni_yori", 2)
            .add_card("kuni_yori_exp", 3)
            .add_card("ambush", 10)
            .add_card("ambush", 11)
            .add_card("ambush", 11)
            .add_card("kyuden_hida", 20)
        )
        yaml = serialize_deck(original, repo, deck_name="Full Trip")
        reimported, name, unresolved = import_deck_yaml(yaml, repo)

        assert name == "Full Trip"
        assert unresolved == []
        assert reimported.cards == original.cards
