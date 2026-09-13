import filecmp
import tempfile

from pathlib import Path

from yasuki_skills import bundle
from yasuki_skills.harnesses import HARNESSES, Harness
from yasuki_skills.install import install_skill, write_references
from yasuki_skills.materialize import MaterializeError


def installed_harnesses(root: Path) -> list[Harness]:
    """Return the harnesses that have a skills directory under ``root``.

    Parameters
    ----------
    root : Path
        The project to look in.

    Returns
    -------
    harnesses : list of Harness
        Those whose directory exists, whatever it holds.
    """
    return [harness for harness in HARNESSES if (root / harness.directory).is_dir()]


def drift(root: Path, docs_root: Path | None = None, source_root: Path | None = None) -> list[str]:
    """Report every way the installed skills differ from what installing now would write.

    Four kinds of difference are reported: a skill that is installed and no longer shipped, a
    skill that is shipped and not installed, a skill whose files differ, and a skill that can no
    longer be rendered at all. The comparison is against a fresh render rather than the packaged
    bytes, so a page whose source moved counts as drift even though the skill itself was never
    touched.

    Parameters
    ----------
    root : Path
        The project to check.
    docs_root : Path or None, optional
        Root of the documentation tree. Default None, meaning the packaged or checkout pages.
    source_root : Path or None, optional
        Directory included source files are resolved against. Default None, meaning the directory
        holding the installed packages.

    Returns
    -------
    reports : list of str
        One line per difference, empty when every installed skill is current.
    """
    harnesses = installed_harnesses(root)

    if not harnesses:
        return []

    docs_root = bundle.docs_source() if docs_root is None else docs_root
    source_root = bundle.source_root() if source_root is None else source_root
    shipped = {skill.name: skill for skill in bundle.available_skills()}

    reports = []
    with tempfile.TemporaryDirectory() as staging:
        fresh = Path(staging)
        unrenderable = {}
        for name, skill in shipped.items():
            install_skill(skill, fresh / name, force=True)

            if docs_root is None:
                continue

            try:
                write_references(skill, fresh / name, docs_root, source_root)
            except MaterializeError as error:
                # Reported rather than raised: a check that dies on the first broken page tells
                # you less than one that lists every skill in trouble.
                unrenderable[name] = str(error)

        for harness in harnesses:
            directory = root / harness.directory
            present = {path.name for path in directory.iterdir() if (path / "SKILL.md").is_file()}

            for name in sorted(present - set(shipped)):
                reports.append(f"{harness.directory}/{name}: installed, no longer shipped")

            for name in sorted(set(shipped) - present):
                reports.append(f"{harness.directory}/{name}: shipped, not installed")

            for name in sorted(present & set(shipped)):
                if name in unrenderable:
                    reports.append(f"{harness.directory}/{name}: {unrenderable[name]}")
                    continue

                comparison = filecmp.dircmp(fresh / name, directory / name)
                reports += [
                    f"{harness.directory}/{name}/{path}: differs from a fresh install"
                    for path in _differing(comparison)
                ]

    return reports


def _differing(comparison: filecmp.dircmp[str]) -> list[str]:
    """Return the paths in ``comparison`` that differ, are missing, or are unexpected."""
    differing = [*comparison.diff_files, *comparison.left_only, *comparison.right_only]

    for name, subdirectory in comparison.subdirs.items():
        differing += [f"{name}/{path}" for path in _differing(subdirectory)]

    return sorted(differing)
