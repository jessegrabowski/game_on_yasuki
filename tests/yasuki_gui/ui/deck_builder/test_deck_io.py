import pytest

from yasuki_core.card_art import CustomPrint, custom_print_id
from yasuki_gui.ui.deck_builder.custom_art import custom_print_record
from yasuki_gui.ui.deck_builder.deck_data import DeckState
from yasuki_gui.ui.deck_builder.deck_io import (
    serialize_deck,
    parse_deck_yaml,
    import_deck_yaml,
)

CARDS = {
    "kuni_yori": {
        "card_id": "kuni_yori",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori",
        "types": ["Personality"],
        "decks": ["Dynasty"],
    },
    "kuni_yori_experienced": {
        "card_id": "kuni_yori_experienced",
        "name": "Kuni Yori",
        "extended_title": "Kuni Yori \u2022 Experienced",
        "types": ["Personality"],
        "decks": ["Dynasty"],
    },
    "ambush": {
        "card_id": "ambush",
        "name": "Ambush",
        "extended_title": "Ambush",
        "types": ["Strategy"],
        "decks": ["Fate"],
    },
    "kyuden_hida": {
        "card_id": "kyuden_hida",
        "name": "Kyuden Hida",
        "extended_title": "Kyuden Hida",
        "types": ["Stronghold"],
        "decks": ["Pre-Game"],
    },
    "700_soldier_plain": {
        "card_id": "700_soldier_plain",
        "name": "700 Soldier Plain",
        "extended_title": "700 Soldier Plain",
        "types": ["Holding"],
        "decks": ["Dynasty"],
    },
}

PRINTS = {
    "kuni_yori": [
        {"print_id": 1, "set_name": "Imperial Edition"},
        {"print_id": 2, "set_name": "Pearl Edition"},
    ],
    "kuni_yori_experienced": [
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
        self._custom = {}

    @property
    def cards_by_id(self):
        return self._cards

    def get_card(self, card_id):
        return self._cards.get(card_id)

    def get_prints(self, card_id):
        base = list(self._prints.get(card_id, []))
        customs = [
            custom_print_record(recipe, self)
            for recipe in self._custom.values()
            if recipe.recipient_card_id == card_id
        ]
        return base + customs

    def register_custom_print(self, recipe):
        print_id = custom_print_id(recipe)
        self._custom[print_id] = recipe
        return print_id

    def get_custom_print(self, print_id):
        return self._custom.get(print_id)


@pytest.fixture
def repo():
    return MockRepository()


class TestSerializeDeck:
    def test_includes_deck_name(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Test Deck")
        assert "name: Test Deck" in yaml

    def test_quotes_name_with_colon(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Deck: Return")
        assert '"Deck: Return"' in yaml

    def test_empty_deck_is_name_and_date(self, repo):
        yaml = serialize_deck(DeckState(), repo, deck_name="Empty", today="2026-06-01")
        assert yaml == "name: Empty\ndate: 2026-06-01\n"

    def test_author_written_when_set_and_round_trips(self, repo):
        state = DeckState().add_card("ambush", 10)
        yaml = serialize_deck(state, repo, deck_name="A", deck_author="Ada", today="2026-06-01")
        assert "author: Ada" in yaml and "date: 2026-06-01" in yaml
        assert parse_deck_yaml(yaml)["author"] == "Ada"

    def test_author_omitted_when_empty(self, repo):
        yaml = serialize_deck(DeckState().add_card("ambush", 10), repo, deck_name="A")
        assert "author:" not in yaml

    def test_section_grouped_by_type_with_counts(self, repo):
        state = DeckState().add_card("kuni_yori", 1).add_card("kuni_yori", 1)
        yaml = serialize_deck(state, repo, deck_name="G")
        # Section header with total; a type subheader. Both are comments the parser skips.
        assert "Dynasty: # (2)" in yaml
        assert len(parse_deck_yaml(yaml)["dynasty"]) == 1

    def test_empty_name_still_serializes(self, repo):
        yaml = serialize_deck(DeckState(), repo)
        assert yaml.startswith("name:")

    def test_omits_empty_sections(self, repo):
        state = DeckState().add_card("ambush", 10)
        yaml = serialize_deck(state, repo)
        assert "Fate:" in yaml
        assert "Dynasty:" not in yaml
        assert "Pre-Game:" not in yaml

    def test_includes_count_prefix_for_multiples(self, repo):
        state = DeckState().add_card("ambush", 10).add_card("ambush", 10)
        yaml = serialize_deck(state, repo)
        assert "2x Ambush" in yaml

    def test_setup_cards_in_pre_game_section(self, repo):
        state = DeckState().add_card("kyuden_hida", 20)
        yaml = serialize_deck(state, repo)
        assert "Pre-Game:" in yaml
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
        state, name, _author, unresolved = import_deck_yaml(yaml, repo)
        assert name == "Test"
        assert unresolved == []
        assert "ambush" in state.cards
        assert state.cards["ambush"] == [(10, 1)]

    def test_imports_with_count(self, repo):
        yaml = "name: T\nfate:\n  - 3x Ambush [Lotus Edition]"
        state, _, _, _ = import_deck_yaml(yaml, repo)
        assert state.cards["ambush"] == [(11, 3)]

    def test_imports_multiple_prints_of_same_card(self, repo):
        yaml = "name: T\nfate:\n  - Ambush [Imperial Edition]\n  - 2x Ambush [Lotus Edition]"
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        prints = state.cards["ambush"]
        assert (10, 1) in prints
        assert (11, 2) in prints

    def test_imports_setup_cards(self, repo):
        yaml = "name: T\npre_game:\n  - Kyuden Hida [Gold Edition]"
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert "kyuden_hida" in state.cards

    def test_distinguishes_base_from_experienced(self, repo):
        yaml = (
            "name: T\ndynasty:\n"
            "  - Kuni Yori [Imperial Edition]\n"
            "  - Kuni Yori \u2022 Experienced [Pearl Edition]"
        )
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert "kuni_yori" in state.cards
        assert "kuni_yori_experienced" in state.cards

    def test_unresolved_names_reported(self, repo):
        yaml = "name: T\nfate:\n  - Nonexistent Card"
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == ["Nonexistent Card"]
        assert state.cards == {}

    def test_falls_back_to_first_print_without_set(self, repo):
        yaml = "name: T\nfate:\n  - Ambush"
        state, _, _, _ = import_deck_yaml(yaml, repo)
        assert state.cards["ambush"] == [(10, 1)]

    def test_mismatched_set_falls_back_to_first_print(self, repo):
        yaml = "name: T\nfate:\n  - Ambush [Nonexistent Set]"
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == []
        assert state.cards["ambush"] == [(10, 1)]

    def test_import_empty_input(self, repo):
        state, name, _author, unresolved = import_deck_yaml("", repo)
        assert state.cards == {}
        assert unresolved == []
        assert name == "Imported Deck"

    def test_full_round_trip(self, repo):
        original = (
            DeckState()
            .add_card("kuni_yori", 1)
            .add_card("kuni_yori", 2)
            .add_card("kuni_yori_experienced", 3)
            .add_card("ambush", 10)
            .add_card("ambush", 11)
            .add_card("ambush", 11)
            .add_card("kyuden_hida", 20)
        )
        yaml = serialize_deck(original, repo, deck_name="Full Trip")
        reimported, name, _author, unresolved = import_deck_yaml(yaml, repo)

        assert name == "Full Trip"
        assert unresolved == []
        assert reimported.cards == original.cards


class TestCustomPrintIO:
    def test_serializes_art_trailer_with_recipient_and_donor(self, repo):
        recipe = CustomPrint("ambush", 10, "kuni_yori", 1)
        custom_id = repo.register_custom_print(recipe)
        yaml = serialize_deck(DeckState().add_card("ambush", custom_id), repo, deck_name="Borrowed")
        assert "Ambush [Imperial Edition] {art: Kuni Yori [Imperial Edition]}" in yaml

    def test_parses_art_trailer(self):
        parsed = parse_deck_yaml(
            "name: T\nfate:\n  - Ambush [Imperial Edition] {art: Kuni Yori [Imperial Edition]}"
        )
        entry = parsed["fate"][0]
        assert entry["name"] == "Ambush"
        assert entry["set_name"] == "Imperial Edition"
        assert entry["art"] == {"name": "Kuni Yori", "set_name": "Imperial Edition"}

    def test_plain_entry_has_no_art(self):
        parsed = parse_deck_yaml("name: T\nfate:\n  - Ambush [Imperial Edition]")
        assert parsed["fate"][0]["art"] is None

    def test_custom_round_trip_reconstructs_recipe_in_fresh_repo(self, repo):
        recipe = CustomPrint("ambush", 10, "kuni_yori", 1)
        custom_id = repo.register_custom_print(recipe)
        yaml = serialize_deck(DeckState().add_card("ambush", custom_id), repo)

        fresh = MockRepository()
        reimported, _, _author, unresolved = import_deck_yaml(yaml, fresh)

        assert unresolved == []
        ((pid, count),) = reimported.cards["ambush"]
        assert count == 1
        assert pid == custom_id
        assert fresh.get_custom_print(pid) == recipe

    def test_unresolvable_donor_falls_back_to_plain_print(self, repo):
        yaml = "name: T\nfate:\n  - Ambush [Imperial Edition] {art: Ghost Card [Nowhere]}"
        state, _, _author, unresolved = import_deck_yaml(yaml, repo)
        assert unresolved == ["Ghost Card"]
        assert state.cards["ambush"] == [(10, 1)]

    def test_round_trip_resolves_non_default_recipient_and_donor_prints(self, repo):
        # Recipient is ambush's Lotus print (11, not the first), donor a non-first kuni_yori print.
        recipe = CustomPrint("ambush", 11, "kuni_yori", 2)
        custom_id = repo.register_custom_print(recipe)
        yaml = serialize_deck(DeckState().add_card("ambush", custom_id), repo)
        assert "Ambush [Lotus Edition] {art: Kuni Yori [Pearl Edition]}" in yaml

        fresh = MockRepository()
        reimported, _, _author, unresolved = import_deck_yaml(yaml, fresh)
        assert unresolved == []
        ((pid, _),) = reimported.cards["ambush"]
        assert fresh.get_custom_print(pid) == recipe

    def test_same_custom_print_stacks(self, repo):
        custom_id = repo.register_custom_print(CustomPrint("ambush", 10, "kuni_yori", 1))
        state = DeckState().add_card("ambush", custom_id).add_card("ambush", custom_id)
        assert state.cards["ambush"] == [(custom_id, 2)]
