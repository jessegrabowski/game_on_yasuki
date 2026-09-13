from pathlib import Path

import pytest

from yasuki_skills.check import drift, installed_harnesses
from yasuki_skills.install import install_skill


@pytest.fixture
def project(tmp_path: Path, skill: Path, monkeypatch) -> Path:
    """A project with the one bundled skill installed for Claude Code, and nothing stale."""
    monkeypatch.setattr("yasuki_skills.bundle.SKILLS_SOURCE", skill.parent)

    root = tmp_path / "project"
    install_skill(skill, root / ".claude" / "skills" / skill.name, force=True)

    return root


def test_a_directory_that_exists_is_checked(project: Path):
    assert [harness.name for harness in installed_harnesses(project)] == ["claude"]


def test_a_directory_that_does_not_exist_is_not(tmp_path: Path):
    assert installed_harnesses(tmp_path) == []


def test_a_current_install_reports_nothing(project: Path):
    assert drift(project, docs_root=None) == []


def test_a_retired_skill_left_behind_is_reported(project: Path):
    """The failure that put six dead skills in a live session."""
    stale = project / ".claude" / "skills" / "rules-engine"
    stale.mkdir()
    (stale / "SKILL.md").write_text("---\nname: rules-engine\n---\n", encoding="utf-8")

    reports = drift(project, docs_root=None)

    assert len(reports) == 1
    assert "rules-engine" in reports[0]
    assert "no longer shipped" in reports[0]


def test_a_skill_that_was_never_installed_is_reported(project: Path, skill: Path):
    second = skill.parent / "card-data"
    second.mkdir()
    (second / "SKILL.md").write_text("---\nname: card-data\n---\n", encoding="utf-8")

    reports = drift(project, docs_root=None)

    assert len(reports) == 1
    assert "card-data" in reports[0]
    assert "not installed" in reports[0]


def test_an_installed_skill_edited_by_hand_is_reported(project: Path, skill: Path):
    edited = project / ".claude" / "skills" / skill.name / "SKILL.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")

    reports = drift(project, docs_root=None)

    assert len(reports) == 1
    assert "SKILL.md" in reports[0]
    assert "differs" in reports[0]


def test_a_page_that_changed_upstream_is_reported(tmp_path: Path, skill: Path, monkeypatch):
    """The skill is untouched; only the page it carries moved, and that is still drift."""
    monkeypatch.setattr("yasuki_skills.bundle.SKILLS_SOURCE", skill.parent)

    docs = tmp_path / "docs" / "contributing"
    docs.mkdir(parents=True)
    page = docs / "adding_a_card.md"
    page.write_text("As printed.\n", encoding="utf-8")
    (skill / "references.txt").write_text("docs/contributing/adding_a_card.md\n", encoding="utf-8")

    root = tmp_path / "project"
    target = root / ".claude" / "skills" / skill.name
    install_skill(skill, target, force=True)
    (target / "references" / "contributing").mkdir(parents=True)
    (target / "references" / "contributing" / "adding_a_card.md").write_text(
        "As printed.\n", encoding="utf-8"
    )

    assert drift(root, docs_root=tmp_path / "docs") == []

    page.write_text("Rewritten upstream.\n", encoding="utf-8")
    reports = drift(root, docs_root=tmp_path / "docs")

    assert len(reports) == 1
    assert "adding_a_card.md" in reports[0]


def test_a_skill_that_cannot_render_is_reported_rather_than_raised(
    tmp_path: Path, skill: Path, monkeypatch
):
    """A check that dies on the first broken page says less than one that lists them all."""
    monkeypatch.setattr("yasuki_skills.bundle.SKILLS_SOURCE", skill.parent)
    (skill / "references.txt").write_text("docs/contributing/deleted.md\n", encoding="utf-8")

    root = tmp_path / "project"
    install_skill(skill, root / ".claude" / "skills" / skill.name, force=True)
    (tmp_path / "docs").mkdir()

    reports = drift(root, docs_root=tmp_path / "docs")

    assert len(reports) == 1
    assert "deleted.md" in reports[0]


def test_a_project_with_nothing_installed_is_not_rendered(tmp_path: Path, monkeypatch):
    """Nothing to compare against means nothing to render, and no docs tree is needed to say so."""
    monkeypatch.setattr("yasuki_skills.bundle.docs_source", lambda: None)
    monkeypatch.setattr(
        "yasuki_skills.bundle.available_skills", lambda *_: pytest.fail("rendered anyway")
    )

    assert drift(tmp_path) == []


def test_a_stray_file_inside_an_installed_skill_is_reported(project: Path, skill: Path):
    """An installed skill is generated output, so anything extra in it came from somewhere else."""
    (project / ".claude" / "skills" / skill.name / "notes.md").write_text(
        "mine\n", encoding="utf-8"
    )

    reports = drift(project, docs_root=None)

    assert len(reports) == 1
    assert "notes.md" in reports[0]
