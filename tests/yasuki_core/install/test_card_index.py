import pytest
import yaml

from yasuki_core.card_identity import current_id, retired_ids
from yasuki_core.install.card_index import (
    DEFAULT_CARDS_PATH,
    card_ids,
    iter_set_entries,
    read_index,
    untagged_title_ties,
    write_index,
)


def write_set(cards_dir, name, cards):
    (cards_dir / f"{name}.yaml").write_text(yaml.safe_dump({"set": name, "cards": cards}))


def test_an_explicit_id_wins_over_the_derived_one(tmp_path):
    write_set(
        tmp_path,
        "shattered_empire",
        [
            {"id": "bayushi_akane", "title": "Bayushi Akane", "subtitle": "Soul of Bayushi Kurumi"},
            {"title": "Shosuro Aoki", "keywords": ["Experienced"]},
        ],
    )

    assert card_ids(tmp_path) == ["bayushi_akane", "shosuro_aoki_experienced"]


def test_a_reverse_face_gets_its_own_suffixed_id(tmp_path):
    # A flip stronghold is two rows sharing a title; without the suffix the back would collide with
    # the front and the index would claim one card where the database holds two.
    write_set(
        tmp_path,
        "gold",
        [{"title": "Kyuden Hida"}, {"title": "Kyuden Hida", "is_back": True}],
    )

    assert card_ids(tmp_path) == ["kyuden_hida", "kyuden_hida__back"]


def test_a_card_printed_in_several_sets_appears_once(tmp_path):
    write_set(tmp_path, "imperial", [{"title": "Modest Farm"}])
    write_set(tmp_path, "gold", [{"title": "Modest Farm"}])

    assert card_ids(tmp_path) == ["modest_farm"]


def test_two_different_cards_claiming_one_id_is_an_error(tmp_path):
    # Token ids are stat-descriptive, so two unlike tokens can land on the same string. Both this
    # index and load_cards keep whichever came first, so the second card would vanish in silence.
    write_set(
        tmp_path,
        "tokens",
        [
            {"title": "Courtier", "id": "courtier_0_3_2"},
            {"title": "Expendable Courtier", "id": "courtier_0_3_2"},
        ],
    )

    with pytest.raises(ValueError, match="'Courtier' and 'Expendable Courtier' both claim id"):
        card_ids(tmp_path)


def test_a_collision_across_two_set_files_is_caught(tmp_path):
    # The first-wins dedup spans files, so the clash need not be inside one.
    write_set(tmp_path, "imperial", [{"title": "Courtier", "id": "courtier_0_3_2"}])
    write_set(tmp_path, "gold", [{"title": "Bushi", "id": "courtier_0_3_2"}])

    with pytest.raises(ValueError, match="both claim id 'courtier_0_3_2'"):
        card_ids(tmp_path)


def test_a_reprint_may_retitle_its_card_by_pinning_the_id(tmp_path):
    write_set(tmp_path, "ivory", [{"title": "Tairao"}])
    write_set(tmp_path, "shattered_empire", [{"id": "tairao", "title": "Chuda Tairao"}])
    write_set(tmp_path, "onyx", [{"title": "Faith In My Clan"}, {"title": "Faith in My Clan"}])

    assert card_ids(tmp_path) == ["faith_in_my_clan", "tairao"]


def test_a_file_that_is_not_a_set_names_itself_in_the_error(tmp_path):
    # An empty YAML parses to None, which would otherwise surface as an AttributeError naming no
    # file and leaving whoever hits it to bisect 130 of them.
    (tmp_path / "truncated.yaml").write_text("")

    with pytest.raises(ValueError, match="truncated.yaml is not a set file"):
        card_ids(tmp_path)


def test_a_directory_with_no_set_files_raises(tmp_path):
    # A mistyped --cards path otherwise reads as "the database is empty", which every check built on
    # the index would then agree with.
    with pytest.raises(ValueError, match="No set files in"):
        card_ids(tmp_path)


def test_set_files_holding_no_cards_raise(tmp_path):
    # Silently emitting nothing would leave every registry check passing against no cards at all.
    write_set(tmp_path, "imperial", [])

    with pytest.raises(ValueError, match="No card ids found"):
        card_ids(tmp_path)


def test_the_written_index_round_trips(tmp_path):
    write_set(tmp_path, "imperial", [{"title": "Modest Farm"}, {"title": "Ancestral Sword"}])
    index_path = tmp_path / "card_ids.txt"

    assert write_index(tmp_path, index_path) == 2
    assert read_index(index_path) == {"modest_farm", "ancestral_sword"}


def test_the_index_is_one_id_per_line(tmp_path):
    # The file is committed and read in diffs, and the pre-commit registry check parses it, so the
    # layout is a contract the round-trip above cannot see.
    write_set(tmp_path, "imperial", [{"title": "Modest Farm"}, {"title": "Ancestral Sword"}])
    index_path = tmp_path / "card_ids.txt"
    write_index(tmp_path, index_path)

    assert index_path.read_text() == "ancestral_sword\nmodest_farm\n"


def test_a_local_set_file_stays_out_of_the_index(tmp_path):
    """A set file one machine holds must not reach the committed index, or every other checkout
    disagrees with it."""
    (tmp_path / "real.yaml").write_text("set: Real\ncards:\n- title: Real Card\n", encoding="utf-8")
    (tmp_path / "fixture.local.yaml").write_text(
        "set: Fixture\ncards:\n- title: Local Card\n", encoding="utf-8"
    )

    scanned = {entry.card_id for entry in iter_set_entries(tmp_path)}

    assert scanned == {"real_card"}


def test_the_committed_index_matches_the_card_yaml():
    # The index is a committed derivative of the YAML, so it can go stale silently: every check
    # built on it would keep passing while naming cards that no longer exist. Reparsing costs about
    # a second, which is why this is the only thing that pays it and the fast readers never have to.
    committed = read_index()
    current = set(card_ids(DEFAULT_CARDS_PATH))

    remedy = "run `pixi run card-index` and commit the result"

    assert committed - current == set(), f"index names cards the YAML no longer has; {remedy}"
    assert current - committed == set(), f"YAML has cards the index is missing; {remedy}"


def test_regenerating_the_index_refuses_to_drop_an_id_that_is_not_retired(tmp_path):
    index_path = tmp_path / "card_ids.txt"
    index_path.write_text("aulus\nmodest_farm\n")
    write_set(tmp_path, "gold", [{"title": "Modest Farm"}])

    with pytest.raises(ValueError, match="aulus"):
        write_index(tmp_path, index_path, retired={})
    assert write_index(tmp_path, index_path, retired={"aulus": None}) == 1


def test_every_retired_id_is_gone_and_names_a_card_that_exists():
    committed = read_index()
    retired = retired_ids()

    assert committed.isdisjoint(retired)
    assert all(current_id(card_id) in committed | {None} for card_id in retired)


SETS = {"Gates of Chaos": "goc", "Chaos Reigns Part III": "cr3", "Ivory Edition": "ivory"}
RELEASED = {"Gates of Chaos": "2013-09-01", "Ivory Edition": "2014-03-24"}
AULUS_RETIRED = {"aulus": "aulus_goc"}


def _ties(tmp_path, cards_by_set, retired=AULUS_RETIRED):
    cards_dir = tmp_path / "sets"
    cards_dir.mkdir()
    for set_name, cards in cards_by_set.items():
        write_set(cards_dir, set_name, cards)
    entries = [
        {"set_name": name, "short_id": short_id, "release_date": RELEASED.get(name)}
        for name, short_id in SETS.items()
    ] + [{"set_name": "Tokens", "short_id": "tok"}]
    set_info = tmp_path / "set_info.yaml"
    set_info.write_text(yaml.safe_dump({"arcs": [{"name": "Arc", "sets": entries}]}))
    return untagged_title_ties(cards_dir, set_info, retired)


def test_two_cards_sharing_a_title_must_each_carry_their_first_sets_id(tmp_path):
    problems = _ties(
        tmp_path,
        {
            "Gates of Chaos": [{"title": "Aulus"}],
            "Chaos Reigns Part III": [{"title": "Aulus", "id": "aulus_2"}],
        },
    )

    assert problems == [
        "aulus shares its title with ['aulus_2']; give every printing the id 'aulus_goc'",
        "aulus_2 shares its title with ['aulus']; give every printing the id 'aulus_cr3'",
    ]


def test_cards_sharing_a_title_pass_once_each_carries_its_sets_id(tmp_path):
    problems = _ties(
        tmp_path,
        {
            "Gates of Chaos": [{"title": "Aulus", "id": "aulus_goc"}],
            "Chaos Reigns Part III": [{"title": "Aulus", "id": "aulus_cr3"}],
        },
    )

    assert problems == []


def test_a_shared_title_must_be_retired_to_one_of_its_cards(tmp_path):
    problems = _ties(
        tmp_path,
        {
            "Gates of Chaos": [{"title": "Aulus", "id": "aulus_goc"}],
            "Chaos Reigns Part III": [{"title": "Aulus", "id": "aulus_cr3"}],
        },
        retired={},
    )

    assert problems == [
        "'aulus' is shared by ['aulus_cr3', 'aulus_goc']; retire it to the card a decklist line "
        "naming no set means"
    ]


def test_cards_sharing_a_title_may_not_share_a_set(tmp_path):
    problems = _ties(
        tmp_path,
        {
            "Gates of Chaos": [
                {"title": "Aulus", "id": "aulus_goc"},
                {"title": "Aulus", "id": "aulus_goc_2"},
            ],
        },
    )

    assert "aulus_goc and aulus_goc_2 share the title 'aulus' and the set 'Gates of Chaos'" in (
        " ".join(problems)
    )


def test_the_first_printing_by_release_date_names_the_tag(tmp_path):
    # Gates of Chaos sorts after Chaos Reigns Part III by file name but was released first, and an
    # undated set counts as the latest.
    problems = _ties(
        tmp_path,
        {
            "Chaos Reigns Part III": [{"title": "Aulus", "id": "aulus_goc"}],
            "Gates of Chaos": [{"title": "Aulus", "id": "aulus_goc"}],
            "Ivory Edition": [{"title": "Aulus", "id": "aulus_ivory"}],
        },
    )

    assert problems == []


def test_tokens_sharing_a_title_are_exempt(tmp_path):
    tokens = [
        {"title": "Courtier", "id": "courtier_0_3_2"},
        {"title": "Courtier", "id": "courtier_0_2_2"},
    ]

    assert _ties(tmp_path, {"Tokens": tokens}, retired={}) == []


def test_a_shared_title_in_a_set_with_no_short_id_names_its_file(tmp_path):
    cards = {
        "Gates of Chaos": [{"title": "Aulus", "id": "aulus_goc"}],
        "Unknown": [{"title": "Aulus"}],
    }

    with pytest.raises(ValueError, match="Unknown.yaml: set_info.yaml gives the set 'Unknown' no"):
        _ties(tmp_path, cards)


def test_no_committed_card_shares_a_title_without_its_sets_id():
    assert untagged_title_ties() == []
