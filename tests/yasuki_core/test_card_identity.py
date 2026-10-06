import pytest

from yasuki_core.card_identity import card_id, card_slug, experience_label, extended_title


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
    "keyword, expected",
    [
        ("Experienced", "Experienced"),
        ("Experienced 2", "Experienced 2"),
        ("Experienced 2KYD", "Experienced 2KYD"),
        ("ExperiencedCoM", "ExperiencedCoM"),
        ("Inexperienced", "Inexperienced"),
        ("Experienced 2 Shinjo Yokatsu", "Experienced 2"),
        ("Experienced Bayushi Tenzan", "Experienced"),
    ],
)
def test_experience_label_keeps_the_level_and_set_code_and_drops_an_alternate_title(
    keyword, expected
):
    assert experience_label(["Unique", keyword]) == expected


def test_a_card_without_an_experience_keyword_has_no_label():
    assert experience_label(["Unique", "Samurai"]) is None


def test_extended_title_appends_the_subtitle_then_the_experience():
    entry = {"title": "Akodo Kano", "subtitle": "Clan Champion", "keywords": ["Experienced 3"]}

    assert extended_title(entry) == "Akodo Kano, Clan Champion • Experienced 3"


def test_splitting_a_subtitle_out_of_the_title_keeps_the_id():
    joined = {"title": "Hida Kozan, Voice of the Empress"}
    split = {"title": "Hida Kozan", "subtitle": "Voice of the Empress"}

    assert card_id(split) == card_id(joined) == "hida_kozan_voice_of_the_empress"


def test_a_reverse_face_appends_its_suffix_to_an_explicit_id():
    assert card_id({"id": "kyuden_hida", "title": "Kyuden Hida", "is_back": True}) == (
        "kyuden_hida__back"
    )
