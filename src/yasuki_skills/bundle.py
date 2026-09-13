from pathlib import Path

PACKAGE_NAME = "yasuki_skills"

PACKAGE_ROOT = Path(__file__).resolve().parent

SKILLS_SOURCE = PACKAGE_ROOT / "skills"

AGENTS_FILE = "AGENTS.md"

INSTRUCTIONS = PACKAGE_ROOT / AGENTS_FILE


def available_skills(source: Path | None = None) -> list[Path]:
    """Return the bundled skill directories, sorted by name.

    A skill is any subdirectory holding a ``SKILL.md``, so adding one needs no registry.

    Parameters
    ----------
    source : Path or None, optional
        Directory to search. Default None, meaning the skills shipped inside the package.

    Returns
    -------
    skills : list of Path
        One directory per skill.
    """
    source = SKILLS_SOURCE if source is None else source

    if not source.is_dir():
        return []

    return sorted(path for path in source.iterdir() if (path / "SKILL.md").is_file())


def is_source_checkout(root: Path, instructions: Path | None = None) -> bool:
    """Say whether ``root`` is the checkout this package's own source lives in.

    Parameters
    ----------
    root : Path
        Directory an install is targeting.
    instructions : Path or None, optional
        The packaged instruction file. Default None, meaning the one inside this package.

    Returns
    -------
    same : bool
        True when ``root`` holds the source of the packaged instruction file.
    """
    instructions = INSTRUCTIONS if instructions is None else instructions
    candidate = root / "src" / PACKAGE_NAME / AGENTS_FILE

    return candidate.is_file() and candidate.resolve() == instructions.resolve()
