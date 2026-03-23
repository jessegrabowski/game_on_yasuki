from unittest.mock import MagicMock

from yasuki_core.install.yaml_to_sql import (
    extract_experience_level,
    parse_legalities,
    detect_is_unique,
    detect_is_proxy,
    parse_collector_number,
    parse_all_numbers,
    choose_primary,
    NumberEntry,
    _batch_upsert_cards,
    _batch_upsert_legalities,
    _batch_upsert_prints,
)


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
        result = parse_legalities(["Imperial", "Jade", "Samurai"])
        assert len(result) == 3
        assert ("Imperial", "legal") in result
        assert ("Jade", "legal") in result
        assert ("Samurai", "legal") in result

    def test_not_legal(self):
        result = parse_legalities(["Not Legal"])
        assert result == [("Not Legal", "not_legal")]

    def test_proxy(self):
        result = parse_legalities(["Proxy"])
        assert result == [("Proxy", "not_legal")]

    def test_mixed(self):
        result = parse_legalities(["Imperial", "Not Legal"])
        assert len(result) == 2
        assert ("Imperial", "legal") in result
        assert ("Not Legal", "not_legal") in result

    def test_none_input(self):
        assert parse_legalities(None) == []

    def test_empty_list(self):
        assert parse_legalities([]) == []


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
        assert detect_is_proxy({"type": "Proxy"}) is True
        assert detect_is_proxy({"type": "proxy"}) is True

    def test_proxy_in_legality(self):
        assert detect_is_proxy({"legality": ["Not Legal - Proxy"]}) is True
        assert detect_is_proxy({"legality": ["not legal proxy"]}) is True

    def test_not_proxy(self):
        assert detect_is_proxy({"type": "Personality"}) is False
        assert detect_is_proxy({"legality": "Imperial"}) is False
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


class TestBatchDeduplication:
    """Verify batch functions deduplicate before sending to Postgres.

    PostgreSQL raises CardinalityViolation when ON CONFLICT DO UPDATE
    encounters duplicate constrained values in the same statement.
    Cards reprinted across sets produce duplicate card_ids.
    """

    def test_cards_deduplicates_by_id_last_wins(self):
        cur = MagicMock()
        row_v1 = (
            "same_id",
            "Name V1",
            "name_v1",
            "Name V1",
            "FATE",
            "Strategy",
            None,
            "",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            None,
            None,
        )
        row_v2 = (
            "same_id",
            "Name V2",
            "name_v2",
            "Name V2",
            "FATE",
            "Strategy",
            None,
            "updated text",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            None,
            None,
        )
        other = (
            "other_id",
            "Other",
            "other",
            "Other",
            "DYNASTY",
            "Holding",
            None,
            "",
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            None,
            None,
        )

        _batch_upsert_cards(cur, [row_v1, other, row_v2])

        sent_rows = cur.executemany.call_args[0][1]
        sent_ids = [r[0] for r in sent_rows]
        assert len(sent_rows) == 2
        assert sent_ids.count("same_id") == 1
        kept = next(r for r in sent_rows if r[0] == "same_id")
        assert kept[1] == "Name V2"

    def test_legalities_deduplicates_by_card_and_format(self):
        cur = MagicMock()
        legalities = [
            ("card_a", "Imperial", "legal"),
            ("card_a", "Imperial", "not_legal"),
            ("card_b", "Jade", "legal"),
        ]
        _batch_upsert_legalities(cur, {"Imperial", "Jade"}, legalities)

        legality_call = cur.executemany.call_args_list[1]
        sent_rows = legality_call[0][1]
        assert len(sent_rows) == 2
        kept = next(r for r in sent_rows if r[0] == "card_a")
        assert kept[2] == "not_legal"

    def test_prints_deduplicates_by_constraint_columns(self):
        cur = MagicMock()
        cur.fetchall.return_value = []
        #                  0           1          2      3     4
        #                  card_id     set_name   code   rar   flavor
        #                  5        6              7           8
        #                  artist   prim_subset    prim_int    cn_raw
        #                  9      10
        #                  notes  image_path
        row_v1 = ("card_a", "Set X", "SX", "C", None, "Art1", None, 1, "1", None, "img1.jpg")
        row_v2 = ("card_a", "Set X", "SX", "R", "flavor", "Art2", None, 1, "1", None, "img2.jpg")

        _batch_upsert_prints(cur, [row_v1, row_v2], {})

        sent_rows = cur.executemany.call_args[0][1]
        assert len(sent_rows) == 1
        assert sent_rows[0][3] == "R"
