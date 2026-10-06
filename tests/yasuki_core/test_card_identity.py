import pytest

from yasuki_core.card_identity import (
    card_id,
    card_slug,
    current_id,
    experience_label,
    extended_title,
    name_index,
    resolve_name,
)


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


# Bayushi Akane's newest printing added a subtitle, so the card pins an id its extended title no
# longer slugs to. The Experienced version shares the bare title.
AKANE = {
    "card_id": "bayushi_akane",
    "name": "Bayushi Akane",
    "extended_title": "Bayushi Akane, Soul of Bayushi Kurumi",
}
AKANE_EXPERIENCED = {
    "card_id": "bayushi_akane_experienced",
    "name": "Bayushi Akane",
    "extended_title": "Bayushi Akane • Experienced",
}
INDEX = name_index([AKANE_EXPERIENCED, AKANE])


@pytest.mark.parametrize(
    "name",
    ["Bayushi Akane", "bayushi akane", "Bayushi Akane, Soul of Bayushi Kurumi"],
    ids=["exported-before-the-reprint", "lowercased", "exported-after-the-reprint"],
)
def test_a_name_resolves_by_its_slug_whichever_extended_title_was_exported(name):
    assert resolve_name(INDEX, name) is AKANE


def test_a_shared_bare_title_never_falls_through_to_another_version():
    assert resolve_name(INDEX, "Bayushi Akane • Experienced") is AKANE_EXPERIENCED
    assert resolve_name(name_index([AKANE_EXPERIENCED]), "Bayushi Akane") is None


def test_an_id_wins_over_another_cards_extended_title():
    impostor = {"card_id": "impostor", "name": "Bayushi Akane", "extended_title": "Bayushi Akane"}

    assert resolve_name(name_index([impostor, AKANE]), "Bayushi Akane") is AKANE


RETIRED = {"yoritomo_nintai_2": "yoritomo_nintai", "old_name": "yoritomo_nintai_2", "lost": None}


def test_a_retired_id_follows_its_chain_to_the_card_it_names_today():
    assert current_id("old_name", RETIRED) == "yoritomo_nintai"
    assert current_id("yoritomo_nintai", RETIRED) == "yoritomo_nintai"
    assert current_id("lost", RETIRED) is None


def test_retired_ids_that_loop_are_an_error():
    with pytest.raises(ValueError, match="cycle"):
        current_id("a", {"a": "b", "b": "a"})


def test_a_decklist_naming_a_retired_id_resolves_to_its_successor():
    nintai = {"card_id": "yoritomo_nintai", "name": "Yoritomo Nintai"}
    index = name_index([nintai], RETIRED)

    assert resolve_name(index, "Yoritomo Nintai 2", RETIRED) is nintai
    assert resolve_name(index, "Lost", RETIRED) is None


def test_a_retired_id_is_not_answered_by_another_cards_extended_title():
    follower = {"card_id": "aulus_goc", "name": "Aulus", "extended_title": "Aulus"}
    personality = {"card_id": "aulus_cr3", "name": "Aulus", "extended_title": "Aulus"}
    retired = {"aulus": "aulus_goc"}
    index = name_index([personality, follower], retired)

    assert resolve_name(index, "Aulus", retired) is follower


FOLLOWER = {
    "card_id": "aulus_goc",
    "name": "Aulus",
    "extended_title": "Aulus",
    "prints": [{"set_name": "Gates of Chaos"}],
}
PERSONALITY = {
    "card_id": "aulus_cr3",
    "name": "Aulus",
    "extended_title": "Aulus",
    "prints": [{"set_name": "Chaos Reigns Part III"}],
}


@pytest.mark.parametrize(
    "set_name, expected",
    [("Chaos Reigns Part III", PERSONALITY), ("Gates of Chaos", FOLLOWER), (None, FOLLOWER)],
    ids=["personality-set", "follower-set", "no-set"],
)
def test_the_line_set_tells_apart_cards_sharing_a_title(set_name, expected):
    retired = {"aulus": "aulus_goc"}
    index = name_index([PERSONALITY, FOLLOWER], retired)

    assert resolve_name(index, "Aulus", set_name, retired) is expected
