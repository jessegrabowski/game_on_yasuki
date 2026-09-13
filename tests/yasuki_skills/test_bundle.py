import re

from pathlib import Path

from yasuki_skills.bundle import (
    SKILLS_SOURCE,
    available_skills,
    docs_source,
    is_source_checkout,
    source_root,
)
from yasuki_skills.install import manifested_pages, write_references


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


def test_every_page_every_skill_names_still_renders(tmp_path: Path):
    """The check that a moved function or a renamed page has not left a hole in a shipped skill.

    It asserts nothing about the prose, so editing a page cannot break it.
    """
    docs = docs_source()
    assert docs is not None

    for skill in available_skills():
        target = tmp_path / skill.name
        write_references(skill, target, docs, source_root())

        for page in manifested_pages(skill):
            rendered = target / "references" / page.removeprefix("docs/")

            assert rendered.is_file()
            assert "literalinclude" not in rendered.read_text(encoding="utf-8")


# Navigation rather than narrative: an index page lists its neighbours, and the agent-skills page
# documents this machinery for a human reader.
UNCLAIMED = {"contributing/index.md", "contributing/agent_skills.md"}

# The Agent Skills specification's limits, at https://agentskills.io/specification.
MAX_NAME = 64

MAX_DESCRIPTION = 1024

FRONTMATTER_NAME = re.compile(r"^name:\s*(\S+)$", re.M)

FRONTMATTER_DESCRIPTION = re.compile(r"^description:\s*>-?\n(.+?)(?=\n\w|\Z)", re.M | re.S)


def test_every_narrative_page_is_carried_by_a_skill():
    """A page no skill routes to is one an agent will never be pointed at."""
    docs = docs_source()
    assert docs is not None

    carried = {
        page.removeprefix("docs/")
        for skill in available_skills()
        for page in manifested_pages(skill)
    }
    written = {
        page.relative_to(docs).as_posix()
        for tree in ("contributing", "design/systems")
        for page in (docs / tree).rglob("*.md")
    }

    assert written - carried - UNCLAIMED == set()


def test_every_skill_conforms_to_the_agent_skills_specification():
    """name must match the directory and stay under 64 characters; description under 1024."""
    for skill in available_skills():
        frontmatter = (skill / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        name = FRONTMATTER_NAME.search(frontmatter)
        description = FRONTMATTER_DESCRIPTION.search(frontmatter)

        assert name is not None, f"{skill.name} declares no name"
        assert description is not None, f"{skill.name} declares no folded description"

        assert name.group(1) == skill.name
        assert len(name.group(1)) <= MAX_NAME
        assert 0 < len(" ".join(description.group(1).split())) <= MAX_DESCRIPTION
