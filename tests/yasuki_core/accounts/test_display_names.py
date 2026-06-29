import re

from yasuki_core.accounts.display_names import random_display_name


def test_random_display_name_is_camelcase_with_a_trailing_number():
    assert re.fullmatch(r"[A-Z][a-zA-Z]+\d{3}", random_display_name())


def test_random_display_name_varies():
    # Not a strict guarantee, but a stuck generator (always one value) is a real bug worth catching.
    assert len({random_display_name() for _ in range(20)}) > 1
