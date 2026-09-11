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
