import os
import shutil

from pathlib import Path

from yasuki_skills import bundle
from yasuki_skills.materialize import MaterializeError, materialize

MANIFEST = "references.txt"

REFERENCES = "references"

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


def manifested_pages(skill: Path) -> list[str]:
    """Return the documentation pages ``skill`` carries, as repository-relative paths.

    Parameters
    ----------
    skill : Path
        A skill directory, which names its pages in ``references.txt``.

    Returns
    -------
    pages : list of str
        One path per line of the manifest, comments and blank lines dropped. Empty when the skill
        carries no manifest.
    """
    manifest = skill / MANIFEST

    if not manifest.is_file():
        return []

    lines = manifest.read_text(encoding="utf-8").splitlines()

    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def write_references(skill: Path, target: Path, docs_root: Path, source_root: Path) -> int:
    """Render the pages ``skill`` names into its installed ``references/`` directory.

    The pages keep their place in the documentation tree, so the links between the ones that
    travel together still resolve.

    Parameters
    ----------
    skill : Path
        The bundled skill, holding the manifest.
    target : Path
        The installed skill directory to write into.
    docs_root : Path
        Root of the documentation tree the manifest's paths are relative to.
    source_root : Path
        Directory included source files are resolved against.

    Returns
    -------
    written : int
        How many pages were rendered.

    Raises
    ------
    MaterializeError
        If the manifest names a page that is not there, or a page will not render.
    """
    pages = manifested_pages(skill)
    relative = [page.removeprefix("docs/") for page in pages]

    for path in relative:
        source = docs_root / path

        if not source.is_file():
            raise MaterializeError(f"{skill.name}: its manifest names {path}, which is not there")

        rendered = materialize(
            source, docs_root=docs_root, source_root=source_root, installed=set(relative)
        )
        destination = target / REFERENCES / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")

    return len(relative)


def install_all(
    skills: list[Path],
    skills_dir: Path,
    *,
    force: bool = False,
    docs_root: Path | None = None,
    source_root: Path | None = None,
) -> list[str]:
    """Install every skill into ``skills_dir``, with the pages each one carries.

    Parameters
    ----------
    skills : list of Path
        The skill directories to install.
    skills_dir : Path
        Directory the skills are written into.
    force : bool, optional
        Replace entries that already exist. Default False.
    docs_root : Path or None, optional
        Root of the documentation tree. Default None, which installs the skills without their
        pages.
    source_root : Path or None, optional
        Directory included source files are resolved against. Default None, meaning the directory
        holding the installed packages.

    Returns
    -------
    reports : list of str
        One line per skill, in the order they were installed.
    """
    reports = []
    for skill in skills:
        target = skills_dir / skill.name
        report = install_skill(skill, target, force=force)

        if docs_root is not None and report.startswith("install"):
            written = write_references(
                skill, target, docs_root, source_root or bundle.source_root()
            )
            report += f"  (+{written} page{'s' if written != 1 else ''})" if written else ""

        reports.append(report)

    return reports


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
