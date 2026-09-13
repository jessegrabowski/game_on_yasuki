from pathlib import Path

PACKAGE_NAME = "yasuki_skills"

PACKAGE_ROOT = Path(__file__).resolve().parent

SKILLS_SOURCE = PACKAGE_ROOT / "skills"

AGENTS_FILE = "AGENTS.md"

INSTRUCTIONS = PACKAGE_ROOT / AGENTS_FILE

REPOSITORY = PACKAGE_ROOT.parents[1]


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


def docs_source() -> Path | None:
    """Locate the documentation pages: packaged in the wheel, else the checkout's own tree.

    Returns
    -------
    docs : Path or None
        Root of the documentation tree, or None when neither is present.
    """
    packaged = PACKAGE_ROOT / "docs"
    if packaged.is_dir():
        return packaged

    repository = REPOSITORY / "docs"

    return repository if repository.is_dir() else None


def source_root() -> Path:
    """Return the directory an installed package's source is resolved against.

    A page includes its samples by repository path (``../../src/yasuki_core/...``). A wheel has no
    ``src/``, so the remainder is resolved against the directory holding the installed packages.

    Returns
    -------
    root : Path
        Where ``yasuki_core`` and its siblings live.
    """
    return PACKAGE_ROOT.parent
