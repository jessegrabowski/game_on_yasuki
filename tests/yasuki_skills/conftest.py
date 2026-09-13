from pathlib import Path

import pytest


@pytest.fixture
def skill(tmp_path: Path) -> Path:
    """A bundled skill to install, in a source directory of its own."""
    source = tmp_path / "bundled" / "implementing-a-card"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: implementing-a-card\n---\n", encoding="utf-8")

    return source


@pytest.fixture
def instructions(tmp_path: Path) -> Path:
    """A packaged instruction file for the link tests to point at."""
    source = tmp_path / "package" / "AGENTS.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Conventions\n", encoding="utf-8")

    return source
