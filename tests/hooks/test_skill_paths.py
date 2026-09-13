import pathlib

from hooks.skill_paths import claims, main, repository_files, unresolved

SKILL = """---
name: implementing-a-card
description: >
  Editing anything under `src/yasuki_core/engine/rules/cards/` fires this.
---

# Implementing a card

The table in `docs/contributing/adding_a_card.md` maps wording to hook. The registry lives in
`registrar.py`, a handler returns effects, and `apply_effect` commits them. A card module is
`cards/<set>.py`.
"""


def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "src/yasuki_core/engine/rules/cards").mkdir(parents=True)
    (tmp_path / "src/yasuki_core/engine/registrar.py").touch()
    (tmp_path / "docs/contributing").mkdir(parents=True)
    (tmp_path / "docs/contributing/adding_a_card.md").touch()

    return tmp_path


def written(tmp_path: pathlib.Path, source: str) -> str:
    skill = tmp_path / "skills" / "implementing-a-card" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(source, encoding="utf-8")

    return str(skill.relative_to(tmp_path))


def test_prose_in_backticks_is_not_a_claim():
    assert "apply_effect" not in claims(SKILL)


def test_a_placeholder_name_is_not_a_claim():
    assert "cards/<set>.py" not in claims(SKILL)


def test_a_bare_module_name_is_a_claim():
    assert "registrar.py" in claims(SKILL)


def test_a_skill_naming_real_paths_reports_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo(tmp_path))

    assert main([written(tmp_path, SKILL)]) == 0
    assert capsys.readouterr().out == ""


def test_a_module_that_moved_is_found_wherever_it_landed(tmp_path):
    """Skills name modules relative to prose, so the check is on the name rather than the path."""
    root = repo(tmp_path)
    moved = root / "src/yasuki_core/engine/rules/board/queries.py"
    moved.parent.mkdir(parents=True)
    moved.touch()

    assert unresolved("`queries.py`", root, repository_files(root)) == []


def test_a_deleted_module_fails_and_is_named(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo(tmp_path))
    stale = SKILL.replace("`registrar.py`", "`flow.py`")

    assert main([written(tmp_path, stale)]) == 1
    assert "flow.py" in capsys.readouterr().out


def test_a_stale_path_in_the_description_fails(tmp_path, monkeypatch, capsys):
    """The description decides whether the skill fires, so it is checked like the body."""
    monkeypatch.chdir(repo(tmp_path))
    stale = SKILL.replace(
        "`src/yasuki_core/engine/rules/cards/`", "`src/yasuki_core/engine/rules/economy.py`"
    )

    assert main([written(tmp_path, stale)]) == 1
    assert "economy.py" in capsys.readouterr().out
