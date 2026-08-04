import yaml

from yasuki_core.install.coverage_report import cards_by_set, coverage


def write_set(cards_dir, name, titles):
    (cards_dir / f"{name}.yaml").write_text(
        yaml.safe_dump({"set": name, "cards": [{"title": title} for title in titles]})
    )


def test_a_reprint_counts_toward_every_set_it_appears_in(tmp_path):
    # 3,110 of the database's cards are reprints. Crediting only the first printing would report a
    # later set as empty when a player can field several of its cards.
    write_set(tmp_path, "imperial", ["Modest Farm", "Ancestral Sword"])
    write_set(tmp_path, "gold", ["Modest Farm"])

    assert cards_by_set(tmp_path) == {
        "imperial": {"modest_farm", "ancestral_sword"},
        "gold": {"modest_farm"},
    }


def test_a_set_with_no_implemented_cards_still_reports(tmp_path):
    # The zero rows are the answer to "is anything from this set playable yet?", so the caller
    # decides whether to show them, not this function.
    by_set = {"imperial": {"modest_farm"}, "gold": {"kyuden_hida"}}

    assert coverage({"modest_farm"}, by_set) == [("imperial", 1, 1), ("gold", 0, 1)]


def test_sets_are_ranked_by_implemented_count_then_name():
    by_set = {"zebra": {"a", "b"}, "alpha": {"a"}, "beta": {"a"}}

    assert coverage({"a", "b"}, by_set) == [("zebra", 2, 2), ("alpha", 1, 1), ("beta", 1, 1)]


def test_an_implemented_id_absent_from_a_set_counts_nowhere():
    # A handler keyed on a card that no set contains is what card_registry rejects; coverage must not
    # quietly inflate a set's tally with it.
    assert coverage({"modest_farm", "ghost_card"}, {"imperial": {"modest_farm"}}) == [
        ("imperial", 1, 1)
    ]


def test_a_set_with_no_cards_is_not_reported_at_all(tmp_path):
    # Rather than a row whose percentage is a division by zero. Malformed and missing set files are
    # iter_set_entries' contract, covered once in test_card_index.py.
    write_set(tmp_path, "imperial", ["Modest Farm"])
    write_set(tmp_path, "empty", [])

    assert cards_by_set(tmp_path) == {"imperial": {"modest_farm"}}
