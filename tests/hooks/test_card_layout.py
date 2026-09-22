import pathlib

import pytest

from hooks.card_layout import main

FARM = """# --- Modest Farm ---


@gold_handler("modest_farm")
def _modest_farm_gold(card, game, seat):
    return 1
"""
PORT = """# --- Teardrop Island ---


@gold_handler("teardrop_island")
def _teardrop_island_gold(card, game, seat):
    return 2
"""
BACK = """# --- Modest Farm (back) ---


register_ability("modest_farm__back", Ability(effects=_modest_farm_effects))
"""


def written(tmp_path: pathlib.Path, source: str) -> str:
    module = tmp_path / "a_set.py"
    module.write_text(source, encoding="utf-8")
    return str(module)


def test_a_module_following_the_layout_reports_nothing(tmp_path, capsys):
    assert main([written(tmp_path, FARM + "\n\n" + PORT)]) == 0
    assert capsys.readouterr().err == ""


def test_sections_out_of_alphabetical_order_are_reported(tmp_path, capsys):
    assert main([written(tmp_path, PORT + "\n\n" + FARM)]) == 1
    assert "modest_farm follows teardrop_island" in capsys.readouterr().err


def test_a_back_header_names_the_reverse_face(tmp_path, capsys):
    assert main([written(tmp_path, FARM + "\n\n" + BACK + "\n\n" + PORT)]) == 0
    assert capsys.readouterr().err == ""


def test_a_back_header_over_the_front_registration_is_reported(tmp_path, capsys):
    misheaded = FARM.replace("# --- Modest Farm ---", "# --- Modest Farm (back) ---")

    assert main([written(tmp_path, misheaded)]) == 1
    assert (
        "the header names modest_farm__back, the block registers modest_farm"
        in capsys.readouterr().err
    )


def test_a_second_header_for_one_card_is_reported(tmp_path, capsys):
    assert main([written(tmp_path, FARM + "\n\n# --- Modest Farm ---\n")]) == 1
    assert "a second header for modest_farm" in capsys.readouterr().err


def test_a_header_naming_another_card_is_reported(tmp_path, capsys):
    misheaded = FARM.replace("# --- Modest Farm ---", "# --- Teardrop Island ---")

    assert main([written(tmp_path, misheaded)]) == 1
    assert (
        "the header names teardrop_island, the block registers modest_farm"
        in capsys.readouterr().err
    )


INTERRUPT = """# --- Okura is Released ---


def _okura_is_released_applies(game, source, effect):
    return True


def _okura_is_released_interrupt(game, source, effect):
    return effect


register_interrupt("okura_is_released", Interrupt(answers=Fear, interrupt=_okura_is_released_interrupt))
"""


def test_an_interrupt_registration_belongs_to_the_header_above_it(tmp_path, capsys):
    # An Interrupt block ahead of another card used to be read as part of the next section, so
    # every header below it named the wrong card.
    assert main([written(tmp_path, FARM + "\n\n" + INTERRUPT + "\n\n" + PORT)]) == 0
    assert capsys.readouterr().err == ""


def test_registrations_split_into_two_runs_are_reported(tmp_path, capsys):
    interleaved = FARM + "\n\n" + PORT + '\n\nregister_event_entry("modest_farm")\n'

    assert main([written(tmp_path, interleaved)]) == 1
    assert "modest_farm is registered in 2 separate runs" in capsys.readouterr().err


def test_a_handler_not_named_for_its_card_is_reported(tmp_path, capsys):
    renamed = FARM.replace("def _modest_farm_gold(", "def _do_the_gold_thing(")

    assert main([written(tmp_path, renamed)]) == 1
    assert "_do_the_gold_thing should start with _modest_farm_" in capsys.readouterr().err


@pytest.mark.parametrize("source", [FARM, PORT])
def test_one_card_alone_is_a_whole_valid_module(tmp_path, source):
    # The checks compare sequences pairwise, so a module with nothing to compare has to pass
    # rather than raise on an empty zip or a one-element window.
    assert main([written(tmp_path, source)]) == 0
