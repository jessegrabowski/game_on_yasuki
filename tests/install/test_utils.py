from app.install.utils import (
    normalize_for_filesystem,
    strip_title,
    process_string,
    normalize_empty,
)


class TestNormalizeForFilesystem:
    def test_basic_normalization(self):
        assert normalize_for_filesystem("Bayushi Kachiko") == "bayushi_kachiko"

    def test_removes_special_characters(self):
        assert (
            normalize_for_filesystem("Mirumoto Tsuda, Emerald Champion")
            == "mirumoto_tsuda_emerald_champion"
        )

    def test_handles_apostrophes(self):
        assert normalize_for_filesystem("Akodo's Legacy") == "akodos_legacy"

    def test_handles_ampersands(self):
        assert normalize_for_filesystem("Duty & Honor") == "duty_and_honor"

    def test_removes_comma_from_numbers(self):
        assert normalize_for_filesystem("1,000 Gold") == "1000_gold"

    def test_strips_leading_trailing_underscores(self):
        assert normalize_for_filesystem("  Test  ") == "test"


class TestStripTitle:
    def test_basic_title_without_marker(self):
        assert strip_title("Bayushi Kachiko") == "bayushi_kachiko"

    def test_experienced_marker(self):
        assert strip_title("Bayushi Kachiko • Experienced") == "bayushi_kachiko_exp"

    def test_inexperienced_marker(self):
        assert strip_title("Bayushi Kachiko • Inexperienced") == "bayushi_kachiko_inexp"

    def test_experienced_2_marker(self):
        assert strip_title("Bayushi Kachiko • Experienced 2") == "bayushi_kachiko_exp_2"

    def test_experienced_3_marker(self):
        assert strip_title("Bayushi Kachiko • Experienced 3") == "bayushi_kachiko_exp_3"

    def test_experienced_com_marker(self):
        assert strip_title("Bayushi Kachiko • ExperiencedCoM") == "bayushi_kachiko_exp_com"

    def test_complex_name_with_marker(self):
        assert (
            strip_title("Mirumoto Tsuda, Emerald Champion • Experienced")
            == "mirumoto_tsuda_emerald_champion_exp"
        )


class TestProcessString:
    def test_strips_whitespace(self):
        assert process_string("  test  ") == "test"

    def test_normalizes_nbsp(self):
        assert process_string("test\xa0value") == "test value"

    def test_normalizes_newlines(self):
        assert process_string("test\nvalue") == "test value"

    def test_collapses_multiple_spaces(self):
        assert process_string("test    value") == "test value"


class TestNormalizeEmpty:
    def test_none_returns_none(self):
        assert normalize_empty(None) is None

    def test_empty_string_returns_none(self):
        assert normalize_empty("") is None

    def test_whitespace_returns_none(self):
        assert normalize_empty("   ") is None

    def test_dash_returns_none(self):
        assert normalize_empty("-") is None

    def test_valid_string_returns_unchanged(self):
        assert normalize_empty("test") == "test"

    def test_number_as_string_returns_unchanged(self):
        assert normalize_empty("123") == "123"
