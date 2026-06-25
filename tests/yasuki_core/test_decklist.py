from yasuki_core.decklist import parse_deck_yaml

# A small but representative export: metadata header, all three sections, counts (both "x" and the
# "×" the deck-builder emits), set suffixes, and an {art: ...} trailer.
SAMPLE = """\
name: Crab Beats
author: Ada
date: 2026-06-25

Pre-Game: # (2)
  # Strongholds (1)
  - Kyuden Hida [Imperial Edition]
  # Senseis (1)
  - Hida Sensei

Dynasty: # (3)
  # Personalities (3)
  - 2x Kuni Yori [Pearl Edition]
  - Hida Kisada [Imperial Edition] {art: Hida Kisada [Obsidian Edition]}

Fate: # (2)
  # Strategies (2)
  - 2× Ambush [Lotus Edition]
"""


def test_parses_metadata_and_section_counts():
    parsed = parse_deck_yaml(SAMPLE)
    assert parsed["name"] == "Crab Beats"
    assert parsed["author"] == "Ada"
    assert parsed["date"] == "2026-06-25"
    assert len(parsed["pre_game"]) == 2
    assert len(parsed["dynasty"]) == 2
    assert len(parsed["fate"]) == 1


def test_splits_count_set_and_name():
    fate = parse_deck_yaml(SAMPLE)["fate"][0]
    assert fate == {"name": "Ambush", "count": 2, "set_name": "Lotus Edition", "art": None}


def test_pre_game_keeps_stronghold_and_sensei_in_order():
    pre = parse_deck_yaml(SAMPLE)["pre_game"]
    assert [entry["name"] for entry in pre] == ["Kyuden Hida", "Hida Sensei"]
    assert pre[1]["set_name"] is None  # no printed set given


def test_parses_art_trailer_into_a_donor_entry():
    kisada = parse_deck_yaml(SAMPLE)["dynasty"][1]
    assert kisada["name"] == "Hida Kisada"
    assert kisada["art"] == {"name": "Hida Kisada", "set_name": "Obsidian Edition"}


def test_quoted_name_with_special_chars_is_unquoted():
    assert parse_deck_yaml('name: "Deck: The Return"')["name"] == "Deck: The Return"


def test_missing_name_falls_back_to_default():
    assert parse_deck_yaml("fate:\n  - Ambush")["name"] == "Imported Deck"


def test_lowercase_keys_and_blank_lines_and_comments_are_handled():
    parsed = parse_deck_yaml("name: T\n# a comment\n\ndynasty:\n  - 3x Kuni Yori\n\n")
    assert parsed["dynasty"] == [{"name": "Kuni Yori", "count": 3, "set_name": None, "art": None}]


def test_malformed_input_yields_empty_sections_without_raising():
    parsed = parse_deck_yaml("this is not a decklist\n: : :\n- orphan line")
    assert parsed["pre_game"] == []
    assert parsed["dynasty"] == []
    assert parsed["fate"] == []


def test_lines_outside_a_known_section_are_ignored():
    parsed = parse_deck_yaml("name: T\nsideboard:\n  - Ambush\nfate:\n  - Kuni Yori")
    assert [e["name"] for e in parsed["fate"]] == ["Kuni Yori"]
    assert parsed["dynasty"] == []


def test_a_leading_number_in_a_card_name_is_not_read_as_a_count():
    parsed = parse_deck_yaml("name: T\nDynasty:\n  - 700 Soldier Plain")
    assert parsed["dynasty"][0] == {
        "name": "700 Soldier Plain",
        "count": 1,
        "set_name": None,
        "art": None,
    }


def test_bullet_character_in_a_card_name_is_preserved():
    parsed = parse_deck_yaml("name: T\nDynasty:\n  - Kuni Yori • Experienced [Pearl Edition]")
    assert parsed["dynasty"][0]["name"] == "Kuni Yori • Experienced"
    assert parsed["dynasty"][0]["set_name"] == "Pearl Edition"


def test_a_card_name_with_leading_dashes_is_preserved():
    parsed = parse_deck_yaml("name: T\nFate:\n  - --Ranged Attack--")
    assert parsed["fate"][0]["name"] == "--Ranged Attack--"
