from pathlib import Path

from yasuki_skills.bundle import (
    SKILLS_SOURCE,
    available_skills,
    docs_source,
    is_source_checkout,
)


def test_the_bundled_skills_are_discovered():
    names = [skill.name for skill in available_skills()]

    assert names
    assert "implementing-a-card" in names


def test_every_bundled_skill_carries_a_skill_file():
    assert all((skill / "SKILL.md").is_file() for skill in available_skills(SKILLS_SOURCE))


def test_a_directory_without_skills_yields_none(tmp_path: Path):
    (tmp_path / "not-a-skill").mkdir()

    assert available_skills(tmp_path) == []


def test_a_missing_directory_yields_none(tmp_path: Path):
    assert available_skills(tmp_path / "absent") == []


def test_the_checkout_holding_the_packaged_file_is_recognized(tmp_path: Path, instructions: Path):
    checkout = tmp_path / "checkout"
    (checkout / "src" / "yasuki_skills").mkdir(parents=True)
    (checkout / "src" / "yasuki_skills" / "AGENTS.md").symlink_to(instructions)

    assert is_source_checkout(checkout, instructions)


def test_a_project_that_merely_installed_the_package_is_not_the_checkout(
    tmp_path: Path, instructions: Path
):
    project = tmp_path / "someone-elses-project"
    project.mkdir()

    assert not is_source_checkout(project, instructions)


def test_a_project_with_its_own_unrelated_instruction_file_is_not_the_checkout(
    tmp_path: Path, instructions: Path
):
    project = tmp_path / "lookalike"
    (project / "src" / "yasuki_skills").mkdir(parents=True)
    (project / "src" / "yasuki_skills" / "AGENTS.md").write_text("theirs\n", encoding="utf-8")

    assert not is_source_checkout(project, instructions)


def test_the_documentation_tree_is_found():
    docs = docs_source()

    assert docs is not None
    assert (docs / "contributing" / "adding_a_card.md").is_file()
