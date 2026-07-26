from yasuki_core.ruleset import SHATTERED_EMPIRE, normalize_clan


def test_normalize_clan_folds_case_suffix_and_surrounding_whitespace():
    for variant in ("Crab", "crab", "Crab Clan", "  Crab Clan  ", "CRAB CLAN"):
        assert normalize_clan(variant) == "crab"


def test_alignment_resolves_variants_and_the_naga_akasha_alias():
    assert SHATTERED_EMPIRE.alignment("Crane Clan ") == "crane"
    assert SHATTERED_EMPIRE.alignment("Naga") == "akasha"
    assert SHATTERED_EMPIRE.alignment("Akasha") == "akasha"


def test_alignment_is_none_for_a_non_alignment_clan():
    assert SHATTERED_EMPIRE.alignment("Fox") is None
    assert SHATTERED_EMPIRE.alignment("Unaligned") is None
