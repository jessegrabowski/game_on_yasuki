from pathlib import Path

import pytest

from yasuki_skills.install import (
    install_all,
    install_skill,
    link_instructions,
    manifested_pages,
)
from yasuki_skills.materialize import MaterializeError


def test_a_skill_is_copied_into_place(tmp_path: Path, skill: Path):
    target = tmp_path / "project" / ".claude" / "skills" / skill.name

    report = install_skill(skill, target)

    assert (target / "SKILL.md").is_file()
    assert report.startswith("install")


def test_a_second_install_preserves_a_local_edit(tmp_path: Path, skill: Path):
    target = tmp_path / "skills" / skill.name
    install_skill(skill, target)
    (target / "SKILL.md").write_text("edited by hand\n", encoding="utf-8")

    report = install_skill(skill, target)

    assert (target / "SKILL.md").read_text(encoding="utf-8") == "edited by hand\n"
    assert report.startswith("skip")


def test_forcing_replaces_the_edit(tmp_path: Path, skill: Path):
    target = tmp_path / "skills" / skill.name
    install_skill(skill, target)
    (target / "SKILL.md").write_text("edited by hand\n", encoding="utf-8")

    install_skill(skill, target, force=True)

    assert "implementing-a-card" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_forcing_over_a_symlink_leaves_what_it_pointed_at(tmp_path: Path, skill: Path):
    """rmtree through a symlink deletes the directory on the other end of it."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep-me.md").write_text("mine\n", encoding="utf-8")

    target = tmp_path / "skills" / skill.name
    target.parent.mkdir(parents=True)
    target.symlink_to(elsewhere)

    install_skill(skill, target, force=True)

    assert (elsewhere / "keep-me.md").is_file()
    assert (target / "SKILL.md").is_file()
    assert not target.is_symlink()


def test_every_skill_lands_in_one_call(tmp_path: Path, skill: Path):
    second = skill.parent / "card-data"
    second.mkdir()
    (second / "SKILL.md").write_text("---\nname: card-data\n---\n", encoding="utf-8")

    reports = install_all([skill, second], tmp_path / "skills")

    assert len(reports) == 2
    assert (tmp_path / "skills" / "card-data" / "SKILL.md").is_file()


def test_the_instruction_names_become_relative_links(tmp_path: Path, instructions: Path):
    root = tmp_path / "checkout"
    root.mkdir()

    link_instructions(root, instructions)

    assert (root / "AGENTS.md").is_symlink()
    assert (root / "CLAUDE.md").is_symlink()
    assert not (root / "AGENTS.md").readlink().is_absolute()
    assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "# Conventions\n"


def test_linking_twice_changes_nothing(tmp_path: Path, instructions: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    link_instructions(root, instructions)

    reports = link_instructions(root, instructions)

    assert all(report.startswith("keep") for report in reports)


def test_a_real_instruction_file_is_never_replaced(tmp_path: Path, instructions: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "AGENTS.md").write_text("someone wrote this\n", encoding="utf-8")

    reports = link_instructions(root, instructions)

    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "someone wrote this\n"
    assert any(line.startswith("skip") and "AGENTS.md" in line for line in reports)
    # One name being spoken for says nothing about the other.
    assert (root / "CLAUDE.md").is_symlink()


def test_a_link_pointing_somewhere_else_is_repointed(tmp_path: Path, instructions: Path):
    root = tmp_path / "checkout"
    root.mkdir()
    stale = tmp_path / "old-instructions.md"
    stale.write_text("stale\n", encoding="utf-8")
    (root / "AGENTS.md").symlink_to(stale)

    link_instructions(root, instructions)

    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "# Conventions\n"
    assert stale.is_file()


def test_forcing_over_a_broken_symlink_installs(tmp_path: Path, skill: Path):
    """A link whose target is gone reports as absent, so the copy has to unlink it first."""
    target = tmp_path / "skills" / skill.name
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "never-existed")

    report = install_skill(skill, target, force=True)

    assert (target / "SKILL.md").is_file()
    assert not target.is_symlink()
    assert report.startswith("install")


def test_a_broken_symlink_is_left_alone_without_force(tmp_path: Path, skill: Path):
    target = tmp_path / "skills" / skill.name
    target.parent.mkdir(parents=True)
    target.symlink_to(tmp_path / "never-existed")

    report = install_skill(skill, target)

    assert target.is_symlink()
    assert report.startswith("skip")


def test_a_skill_carries_the_pages_its_manifest_names(tmp_path: Path, skill: Path):
    docs = tmp_path / "docs" / "contributing"
    docs.mkdir(parents=True)
    (docs / "adding_a_card.md").write_text("How to add a card.\n", encoding="utf-8")
    (skill / "references.txt").write_text("docs/contributing/adding_a_card.md\n", encoding="utf-8")

    reports = install_all([skill], tmp_path / "skills", docs_root=tmp_path / "docs")
    page = tmp_path / "skills" / skill.name / "references" / "contributing" / "adding_a_card.md"

    assert page.read_text(encoding="utf-8") == "How to add a card.\n"
    assert reports[0].endswith("(+1 page)")


def test_a_skill_without_a_manifest_carries_nothing(tmp_path: Path, skill: Path):
    (tmp_path / "docs").mkdir()

    install_all([skill], tmp_path / "skills", docs_root=tmp_path / "docs")

    assert not (tmp_path / "skills" / skill.name / "references").exists()


def test_a_manifest_naming_a_page_that_is_gone_fails_the_install(tmp_path: Path, skill: Path):
    """Shipping the skill without the page it routes to is the failure worth crashing over."""
    (tmp_path / "docs").mkdir()
    (skill / "references.txt").write_text("docs/contributing/deleted.md\n", encoding="utf-8")

    with pytest.raises(MaterializeError, match="deleted.md"):
        install_all([skill], tmp_path / "skills", docs_root=tmp_path / "docs")


def test_comments_and_blank_lines_are_not_pages(tmp_path: Path, skill: Path):
    (skill / "references.txt").write_text(
        "# the reading order for a first card\n\ndocs/contributing/adding_a_card.md\n",
        encoding="utf-8",
    )

    assert manifested_pages(skill) == ["docs/contributing/adding_a_card.md"]
