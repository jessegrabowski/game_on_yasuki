import os
import shutil

from pathlib import Path

from yasuki_skills import bundle

INSTRUCTION_NAMES = (bundle.AGENTS_FILE, "CLAUDE.md")


def install_skill(source: Path, target: Path, *, force: bool = False) -> str:
    """Copy one skill into place, leaving anything already there alone unless ``force``.

    The skill is copied rather than symlinked, so it survives the package being upgraded or removed.

    Parameters
    ----------
    source : Path
        The bundled skill directory to copy.
    target : Path
        Where the skill should land.
    force : bool, optional
        Replace ``target`` if something is already there, discarding it. Default False.

    Returns
    -------
    report : str
        One line saying what happened, for printing.
    """
    if target.exists() or target.is_symlink():
        if not force:
            return f"skip     {target.name}  (exists; pass --force to replace)"

        # A symlink is unlinked, never followed: rmtree through one deletes what it points at.
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)

    return f"install  {target.name}"


def install_all(skills: list[Path], skills_dir: Path, *, force: bool = False) -> list[str]:
    """Install every skill into ``skills_dir``.

    Parameters
    ----------
    skills : list of Path
        The skill directories to install.
    skills_dir : Path
        Directory the skills are written into.
    force : bool, optional
        Replace entries that already exist. Default False.

    Returns
    -------
    reports : list of str
        One line per skill, in the order they were installed.
    """
    return [install_skill(skill, skills_dir / skill.name, force=force) for skill in skills]


def link_instructions(root: Path, source: Path | None = None) -> list[str]:
    """Point the instruction names under ``root`` at the packaged instruction file.

    The links are relative, and a real file is never replaced: it belongs to whoever wrote it.

    Parameters
    ----------
    root : Path
        The checkout to write the links into.
    source : Path or None, optional
        The file to point at. Default None, meaning the packaged instruction file.

    Returns
    -------
    reports : list of str
        One line per name, for printing.
    """
    source = bundle.INSTRUCTIONS if source is None else source
    relative = Path(os.path.relpath(source.resolve(), root.resolve()))

    reports = []
    for name in INSTRUCTION_NAMES:
        target = root / name

        if target.is_symlink():
            if target.resolve() == source.resolve():
                reports.append(f"keep     {name}  (already linked)")
                continue

            target.unlink()

        elif target.exists():
            reports.append(f"skip     {name}  (a real file is already there)")
            continue

        target.symlink_to(relative)
        reports.append(f"link     {name}  -> {relative}")

    return reports
