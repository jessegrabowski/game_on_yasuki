import pathlib
import re
import sys

BACKTICKED = re.compile(r"`([^`\s]+)`")

ROOTS = ("src/", "docs/", "tests/", "hooks/", "scripts/")

SEARCHED = ("src", "docs", "tests", "hooks", "scripts")

PRUNED = {".git", ".pixi", ".venv", "__pycache__", "node_modules", "_build", ".ruff_cache"}

# A skill writes a placeholder where the name varies by card or set, as in ``cards/<set>.py``.
PLACEHOLDER = re.compile(r"[<>*]")


def claims(text: str) -> list[str]:
    """Return the backticked tokens in ``text`` that assert a file exists.

    Two forms qualify. A token under one of the source trees is a path claim in itself. A bare
    module name -- ``ops.py``, ``services/actions.py`` -- is one too: skills name modules relative
    to a directory given in the surrounding prose, and a renamed module is the way these notes rot.

    Parameters
    ----------
    text : str
        The contents of a ``SKILL.md``, frontmatter included. The frontmatter is not skipped: the
        description decides whether the skill is loaded at all, so a stale name there is the
        costliest kind.

    Returns
    -------
    claimed : list of str
        The tokens to resolve, in the order they appear.
    """
    found = []
    for token in BACKTICKED.findall(text):
        token = token.rstrip(".,;:")

        if PLACEHOLDER.search(token):
            continue

        if token.startswith(ROOTS) or token.endswith((".py", ".md", ".yaml", ".txt")):
            found.append(token)

    return found


def repository_files(repo: pathlib.Path) -> set[str]:
    """Return every file under the searched trees, as a path relative to ``repo``."""
    found = set()
    for root in SEARCHED:
        for path in (repo / root).rglob("*"):
            if path.is_file() and not PRUNED & set(path.parts):
                found.add(path.relative_to(repo).as_posix())

    return found


def unresolved(text: str, repo: pathlib.Path, files: set[str]) -> list[str]:
    """Return the claims in ``text`` that name nothing under ``repo``."""
    missing = []
    for claim in claims(text):
        if claim.startswith(ROOTS):
            if not (repo / claim).exists():
                missing.append(claim)
            continue

        if not any(path.endswith("/" + claim) for path in files):
            missing.append(claim)

    return missing


def main(argv: list[str] | None = None) -> int:
    """Report every path a SKILL.md names that does not exist.

    Parameters
    ----------
    argv : list of str, optional
        The files to check, as pre-commit passes them. Default None, meaning ``sys.argv[1:]``.

    Returns
    -------
    status : int
        Zero when every claim resolves.
    """
    argv = sys.argv[1:] if argv is None else argv
    repo = pathlib.Path.cwd()
    files = repository_files(repo)

    failed = 0
    for name in argv:
        skill = pathlib.Path(name)

        for claim in unresolved(skill.read_text(encoding="utf-8"), repo, files):
            print(f"{skill}: names nothing in the repository: {claim}")
            failed = 1

    return failed


if __name__ == "__main__":
    sys.exit(main())
