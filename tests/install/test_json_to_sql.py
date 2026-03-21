from app.install.json_to_sql import (
    parse_int_token,
    parse_fc,
    parse_hr_cost_ph,
    parse_ps_gp_sh,
    parse_keywords,
    extract_experience_level,
    parse_legalities,
    detect_is_unique,
    detect_is_proxy,
    parse_collector_number,
    parse_all_numbers,
    choose_primary,
    NumberEntry,
)


class TestParseIntToken:
    def test_positive_int(self):
        assert parse_int_token("3") == 3
        assert parse_int_token("42") == 42

    def test_negative_int(self):
        assert parse_int_token("-2") == -2
        assert parse_int_token("-10") == -10

    def test_plus_prefix(self):
        assert parse_int_token("+1") == 1
        assert parse_int_token("+5") == 5

    def test_dash_means_none(self):
        assert parse_int_token("-") is None

    def test_empty_means_none(self):
        assert parse_int_token("") is None
        assert parse_int_token("   ") is None

    def test_none_input(self):
        assert parse_int_token(None) is None

    def test_invalid_returns_none(self):
        assert parse_int_token("abc") is None
        assert parse_int_token("1.5") is None


class TestParseFC:
    def test_standard_format(self):
        assert parse_fc("1 2") == (1, 2)
        assert parse_fc("3 4") == (3, 4)

    def test_with_plus(self):
        assert parse_fc("1 +1") == (1, 1)
        assert parse_fc("+0 +1") == (0, 1)

    def test_missing_value(self):
        assert parse_fc("1") == (1, None)

    def test_none_input(self):
        assert parse_fc(None) == (None, None)

    def test_empty_input(self):
        assert parse_fc("") == (None, None)


class TestParseHRCostPH:
    def test_standard_format(self):
        assert parse_hr_cost_ph("2 7 1") == (2, 7, 1)

    def test_with_dash(self):
        assert parse_hr_cost_ph("- 7 1") == (None, 7, 1)
        assert parse_hr_cost_ph("2 5 -") == (2, 5, None)
        assert parse_hr_cost_ph("- 0 0") == (None, 0, 0)

    def test_missing_values(self):
        assert parse_hr_cost_ph("1 0") == (1, 0, None)

    def test_none_input(self):
        assert parse_hr_cost_ph(None) == (None, None, None)


class TestParsePSGPSH:
    def test_standard_format(self):
        assert parse_ps_gp_sh("7 4 2") == (7, 4, 2)

    def test_with_plus(self):
        assert parse_ps_gp_sh("+0 +0 -2") == (0, 0, -2)

    def test_partial_values(self):
        assert parse_ps_gp_sh("10  ") == (10, None, None)

    def test_none_input(self):
        assert parse_ps_gp_sh(None) == (None, None, None)


class TestParseKeywords:
    def test_standard_format(self):
        result = parse_keywords("Unique • Air • Shadowlands")
        assert result == ["Unique", "Air", "Shadowlands"]

    def test_single_keyword(self):
        result = parse_keywords("Unique")
        assert result == ["Unique"]

    def test_with_spaces(self):
        result = parse_keywords("Experienced • Soul of the Crane")
        assert result == ["Experienced", "Soul of the Crane"]

    def test_none_input(self):
        assert parse_keywords(None) == []

    def test_empty_input(self):
        assert parse_keywords("") == []


class TestExtractExperienceLevel:
    def test_base_version(self):
        assert extract_experience_level([]) is None
        assert extract_experience_level(["Unique", "Air"]) is None

    def test_inexperienced(self):
        assert extract_experience_level(["Inexperienced"]) == "inexp"
        assert extract_experience_level(["inexperienced"]) == "inexp"

    def test_experienced(self):
        assert extract_experience_level(["Experienced"]) == "exp"

    def test_experienced_numbered(self):
        assert extract_experience_level(["Experienced 2"]) == "exp2"
        assert extract_experience_level(["Experienced 3"]) == "exp3"
        assert extract_experience_level(["Experienced 4"]) == "exp4"
        assert extract_experience_level(["Experienced2"]) == "exp2"

    def test_experienced_campaign(self):
        assert extract_experience_level(["ExperiencedCoM"]) == "exp_com"
        assert extract_experience_level(["Experienced2KYD"]) == "exp2kyd"

    def test_ignores_soul_of(self):
        result = extract_experience_level(["Soul of the Crane", "Experienced"])
        assert result == "exp"


class TestParseLegalities:
    def test_standard_format(self):
        result = parse_legalities("Imperial • Jade • Samurai")
        assert len(result) == 3
        assert ("Imperial", "legal") in result
        assert ("Jade", "legal") in result
        assert ("Samurai", "legal") in result

    def test_not_legal(self):
        result = parse_legalities("Not Legal")
        assert result == [("Not Legal", "not_legal")]

    def test_proxy(self):
        result = parse_legalities("Proxy")
        assert result == [("Proxy", "not_legal")]

    def test_mixed(self):
        result = parse_legalities("Imperial • Not Legal")
        assert len(result) == 2
        assert ("Imperial", "legal") in result
        assert ("Not Legal", "not_legal") in result

    def test_none_input(self):
        assert parse_legalities(None) == []


class TestDetectIsUnique:
    def test_unique_keyword(self):
        assert detect_is_unique(["Unique"]) is True
        assert detect_is_unique(["unique"]) is True
        assert detect_is_unique(["UNIQUE"]) is True

    def test_not_unique(self):
        assert detect_is_unique([]) is False
        assert detect_is_unique(["Air", "Experienced"]) is False


class TestDetectIsProxy:
    def test_proxy_type(self):
        assert detect_is_proxy({"Type": "Proxy"}) is True
        assert detect_is_proxy({"Type": "proxy"}) is True

    def test_proxy_in_legality(self):
        assert detect_is_proxy({"Legality": "Not Legal - Proxy"}) is True
        assert detect_is_proxy({"Legality": "not legal proxy"}) is True

    def test_not_proxy(self):
        assert detect_is_proxy({"Type": "Personality"}) is False
        assert detect_is_proxy({"Legality": "Imperial"}) is False
        assert detect_is_proxy({}) is False


class TestParseCollectorNumber:
    def test_simple_number(self):
        assert parse_collector_number("109") == (None, 109, "109")
        assert parse_collector_number("42") == (None, 42, "42")

    def test_with_subset(self):
        assert parse_collector_number("Lion 41") == ("Lion", 41, "Lion 41")
        assert parse_collector_number("Dragon 00") == ("Dragon", 0, "Dragon 00")

    def test_with_leading_zeros(self):
        assert parse_collector_number("Lion 09") == ("Lion", 9, "Lion 09")

    def test_none_input(self):
        assert parse_collector_number(None) == (None, None, None)

    def test_empty_input(self):
        assert parse_collector_number("") == (None, None, None)
        assert parse_collector_number("   ") == (None, None, None)

    def test_no_digits(self):
        raw = "Special"
        assert parse_collector_number(raw) == (None, None, raw)


class TestParseAllNumbers:
    def test_single_number(self):
        result = parse_all_numbers("109")
        assert result == [NumberEntry(None, 109)]

    def test_single_with_subset(self):
        result = parse_all_numbers("Lion 09")
        assert result == [NumberEntry("Lion", 9)]

    def test_multiple_numbers(self):
        result = parse_all_numbers("Unicorn 07,Unicorn 20")
        assert result == [
            NumberEntry("Unicorn", 7),
            NumberEntry("Unicorn", 20),
        ]

    def test_mixed_subsets(self):
        result = parse_all_numbers("Lion 10,Lion 17,Shadowlands 20")
        assert len(result) == 3
        assert NumberEntry("Lion", 10) in result
        assert NumberEntry("Lion", 17) in result
        assert NumberEntry("Shadowlands", 20) in result

    def test_none_input(self):
        assert parse_all_numbers(None) == []

    def test_empty_input(self):
        assert parse_all_numbers("") == []


class TestChoosePrimary:
    def test_single_entry(self):
        entries = [NumberEntry("Lion", 10)]
        assert choose_primary(entries) == ("Lion", 10)

    def test_chooses_smallest(self):
        entries = [
            NumberEntry("Lion", 10),
            NumberEntry("Lion", 17),
            NumberEntry("Shadowlands", 20),
        ]
        assert choose_primary(entries) == ("Lion", 10)

    def test_empty_list(self):
        assert choose_primary([]) == (None, None)

    def test_with_none_subset(self):
        entries = [
            NumberEntry(None, 5),
            NumberEntry("Lion", 10),
        ]
        assert choose_primary(entries) == (None, 5)
