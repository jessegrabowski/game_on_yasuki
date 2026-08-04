import pytest
import yaml

from yasuki_core.install.card_index import card_ids, read_index, write_index


def write_set(cards_dir, name, cards):
    (cards_dir / f"{name}.yaml").write_text(yaml.safe_dump({"set": name, "cards": cards}))


def test_ids_come_from_explicit_id_then_extended_title_then_title(tmp_path):
    # The first entry carries all three, so the assertion pins the precedence and not merely that each
    # source works on its own.
    write_set(
        tmp_path,
        "imperial",
        [
            {
                "title": "Ancestral Sword",
                "extended_title": "Ancestral Sword of the Crab",
                "id": "ancestral_sword_promo",
            },
            {"title": "Shosuro Aoki", "extended_title": "Shosuro Aoki Experienced"},
            {"title": "Modest Farm"},
        ],
    )

    assert card_ids(tmp_path) == [
        "ancestral_sword_promo",
        "modest_farm",
        "shosuro_aoki_experienced",
    ]


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


def test_a_file_that_is_not_a_set_names_itself_in_the_error(tmp_path):
    # An empty YAML parses to None, which would otherwise surface as an AttributeError naming no file
    # — leaving whoever hits it to bisect 130 of them.
    (tmp_path / "truncated.yaml").write_text("")

    with pytest.raises(ValueError, match="truncated.yaml is not a set file"):
        card_ids(tmp_path)


def test_an_empty_directory_raises_rather_than_writing_an_empty_index(tmp_path):
    # Silently emitting nothing would leave every registry check passing against no cards at all.
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
