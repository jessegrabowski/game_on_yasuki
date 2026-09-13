from pathlib import Path

from yasuki_skills.agents_file import BLOCK_START
from yasuki_skills.cli import chosen, install, main
from yasuki_skills.harnesses import HARNESSES


def test_listing_the_skills_exits_zero(capsys):
    assert main(["--list"]) == 0
    assert "implementing-a-card" in capsys.readouterr().out


def test_no_flag_means_every_harness():
    assert chosen(None) == list(HARNESSES)


def test_naming_harnesses_narrows_it_in_declaration_order():
    assert [harness.name for harness in chosen(["claude", "agents"])] == ["agents", "claude"]


def test_a_project_gets_every_directory_and_an_owned_block(tmp_path: Path, skill: Path):
    install(tmp_path, [skill], chosen(None), force=False)

    for harness in HARNESSES:
        assert (tmp_path / harness.directory / skill.name / "SKILL.md").is_file()

    assert BLOCK_START in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_narrowing_writes_nothing_else(tmp_path: Path, skill: Path):
    install(tmp_path, [skill], chosen(["claude"]), force=False)

    assert (tmp_path / ".claude" / "skills" / skill.name).is_dir()
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".cursor").exists()


def test_the_source_checkout_is_linked_rather_than_given_a_block(
    tmp_path: Path, skill: Path, instructions: Path, monkeypatch
):
    monkeypatch.setattr("yasuki_skills.bundle.INSTRUCTIONS", instructions)

    checkout = tmp_path / "checkout"
    (checkout / "src" / "yasuki_skills").mkdir(parents=True)
    (checkout / "src" / "yasuki_skills" / "AGENTS.md").symlink_to(instructions)

    install(checkout, [skill], chosen(["agents"]), force=False)

    assert (checkout / "AGENTS.md").is_symlink()
    assert BLOCK_START not in (checkout / "AGENTS.md").read_text(encoding="utf-8")


def test_the_entry_point_installs_into_the_current_directory(
    tmp_path: Path, skill: Path, monkeypatch
):
    """`main` takes no path argument, so the working directory is the whole target contract."""
    monkeypatch.setattr("yasuki_skills.bundle.SKILLS_SOURCE", skill.parent)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)

    assert main(["--harness", "claude"]) == 0
    assert (project / ".claude" / "skills" / skill.name / "SKILL.md").is_file()
    assert BLOCK_START in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_a_package_carrying_no_skills_is_an_error(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr("yasuki_skills.bundle.SKILLS_SOURCE", tmp_path / "empty")
    monkeypatch.chdir(tmp_path)

    assert main([]) == 1
    assert "No skills found" in capsys.readouterr().err
