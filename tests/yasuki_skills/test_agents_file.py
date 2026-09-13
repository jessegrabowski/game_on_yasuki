from pathlib import Path

import pytest

from yasuki_skills.agents_file import BLOCK_END, BLOCK_START, agents_block, update_instructions

BLOCK = f"{BLOCK_START}\n\nthe conventions\n\n{BLOCK_END}\n"


def test_the_shipped_block_carries_both_markers():
    block = agents_block()

    assert block.startswith(BLOCK_START)
    assert block.rstrip("\n").endswith(BLOCK_END)


def test_the_block_is_appended_when_the_file_has_none(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text("# Their project\n\nTheir rules.\n", encoding="utf-8")

    report = update_instructions(path, BLOCK)
    body = path.read_text(encoding="utf-8")

    assert body.startswith("# Their project")
    assert BLOCK_START in body
    assert report.endswith("(block appended)")


def test_the_block_is_replaced_in_place(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"before\n\n{BLOCK_START}\nold\n{BLOCK_END}\n\nafter\n", encoding="utf-8")

    report = update_instructions(path, BLOCK)
    body = path.read_text(encoding="utf-8")

    assert body.startswith("before")
    assert body.endswith("after\n")
    assert "old" not in body
    assert "the conventions" in body
    assert report.endswith("(block replaced)")


def test_a_file_with_one_marker_is_left_alone(tmp_path: Path):
    """Half-marked, the file cannot be edited safely, and it is not the installer's file."""
    path = tmp_path / "AGENTS.md"
    original = f"theirs\n\n{BLOCK_START}\nand nothing closing it\n"
    path.write_text(original, encoding="utf-8")

    report = update_instructions(path, BLOCK)

    assert path.read_text(encoding="utf-8") == original
    assert report.endswith("(markers are unbalanced; left alone)")


def test_a_missing_file_is_created_holding_only_the_block(tmp_path: Path):
    path = tmp_path / "AGENTS.md"

    update_instructions(path, BLOCK)

    assert path.read_text(encoding="utf-8") == BLOCK


def test_a_second_run_leaves_one_copy_of_the_block(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    update_instructions(path, BLOCK)

    update_instructions(path, BLOCK)

    assert path.read_text(encoding="utf-8").count(BLOCK_START) == 1


def test_a_symlink_is_left_alone(tmp_path: Path):
    """Writing through one edits its target, which in a checkout is the packaged instruction file."""
    packaged = tmp_path / "package" / "AGENTS.md"
    packaged.parent.mkdir()
    packaged.write_text("# Conventions\n", encoding="utf-8")

    link = tmp_path / "AGENTS.md"
    link.symlink_to(packaged)

    report = update_instructions(link, BLOCK)

    assert packaged.read_text(encoding="utf-8") == "# Conventions\n"
    assert link.is_symlink()
    assert report.endswith("(a symlink; left alone)")


def test_a_directory_where_the_file_belongs_is_left_alone(tmp_path: Path):
    path = tmp_path / "AGENTS.md"
    path.mkdir()

    report = update_instructions(path, BLOCK)

    assert path.is_dir()
    assert report.endswith("(a directory is already there)")


def test_a_file_holding_two_blocks_is_left_alone(tmp_path: Path):
    """Replacing one of them would leave the other standing as though it were current."""
    path = tmp_path / "AGENTS.md"
    original = (
        f"a\n\n{BLOCK_START}\nfirst\n{BLOCK_END}\n\nb\n\n{BLOCK_START}\nsecond\n{BLOCK_END}\n"
    )
    path.write_text(original, encoding="utf-8")

    report = update_instructions(path, BLOCK)

    assert path.read_text(encoding="utf-8") == original
    assert report.endswith("(more than one block; left alone)")


@pytest.mark.parametrize(
    "ending", ["no trailing newline", "one trailing newline\n", "a blank line already\n\n"]
)
def test_exactly_one_blank_line_separates_the_block_from_what_was_there(
    tmp_path: Path, ending: str
):
    """Whatever the file ends with, appending must not run into it or leave a gap."""
    path = tmp_path / "AGENTS.md"
    path.write_text(ending, encoding="utf-8")

    update_instructions(path, BLOCK)

    assert path.read_text(encoding="utf-8") == ending.rstrip("\n") + "\n\n" + BLOCK
