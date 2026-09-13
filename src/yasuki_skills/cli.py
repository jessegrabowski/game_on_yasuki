import argparse
import sys

from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from yasuki_skills import bundle
from yasuki_skills.agents_file import agents_block, update_instructions
from yasuki_skills.harnesses import BY_NAME, HARNESSES, Harness
from yasuki_skills.install import install_all, link_instructions


def _row(harness: Harness, number: int | None = None) -> str:
    """Format one harness as a line of the help text or of the prompt."""
    lead = f"  {number}  " if number is not None else "  "

    return f"{lead}{harness.name:9} {harness.directory:18} {harness.reads}"


def _build_parser() -> argparse.ArgumentParser:
    reads = "\n".join(_row(harness) for harness in HARNESSES)

    parser = argparse.ArgumentParser(
        prog="yasuki-install-skills",
        description=(
            "Install the game-on-yasuki agent skills into the current project. Skills follow the "
            "Agent Skills standard, so one copy serves every agent that implements it; the only "
            "difference between agents is which directory they read. Pass --harness to choose, or "
            "run with no arguments to be asked.\n\n" + reads
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--harness",
        action="append",
        choices=sorted(BY_NAME),
        metavar="NAME",
        help="Write this agent's directory. Repeatable. Omit to be asked.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace a skill that is already installed."
    )
    parser.add_argument("--list", action="store_true", help="List the bundled skills and exit.")

    return parser


def chosen(names: list[str]) -> list[Harness]:
    """Return the named harnesses, in declaration order and without repeats.

    Parameters
    ----------
    names : list of str
        Harness names, as ``--harness`` or the prompt accepts them.

    Returns
    -------
    harnesses : list of Harness
        Those asked for.
    """
    wanted = set(names)

    return [harness for harness in HARNESSES if harness.name in wanted]


def parse_selection(answer: str) -> list[str]:
    """Read a reply to the prompt as harness names.

    Accepts names, the numbers shown beside them, "all", or any mix, separated by spaces or
    commas. An unrecognized token yields no names at all rather than a partial install.

    Parameters
    ----------
    answer : str
        What the user typed.

    Returns
    -------
    names : list of str
        The harnesses chosen, empty when the reply was empty or held anything unrecognized.
    """
    tokens = [token for token in answer.replace(",", " ").split() if token]

    if not tokens:
        return []

    if any(token.lower() == "all" for token in tokens):
        return [harness.name for harness in HARNESSES]

    names = []
    for token in tokens:
        if token.isdigit() and 1 <= int(token) <= len(HARNESSES):
            names.append(HARNESSES[int(token) - 1].name)
        elif token.lower() in BY_NAME:
            names.append(token.lower())
        else:
            return []

    return names


def ask(out: TextIO | None = None, read: Callable[[str], str] = input) -> list[str]:
    """Ask which agents should read the skills, and return the names chosen.

    Parameters
    ----------
    out : file object or None, optional
        Where the listing is printed. Default None, meaning ``sys.stdout``.
    read : callable, optional
        How the reply is read. Default :func:`input`.

    Returns
    -------
    names : list of str
        The harnesses chosen, empty when the reply was empty or unrecognized.
    """
    out = sys.stdout if out is None else out
    print("\nWhich agents should read these skills?\n", file=out)
    for number, harness in enumerate(HARNESSES, 1):
        print(_row(harness, number), file=out)
    print('\nNumbers or names, separated by spaces, or "all".', file=out)

    try:
        return parse_selection(read("Install for: "))
    except EOFError:
        return []


def install(root: Path, skills: list[Path], harnesses: list[Harness], *, force: bool) -> list[str]:
    """Install the skills into ``root``, and give it an instruction file.

    Parameters
    ----------
    root : Path
        The project to install into.
    skills : list of Path
        The skill directories to install.
    harnesses : list of Harness
        The agents whose directories to write.
    force : bool
        Replace skills that are already installed.

    Returns
    -------
    reports : list of str
        One line per thing written or skipped, for printing.
    """
    reports = []
    for harness in harnesses:
        reports.append(f"{harness.name}:")
        installed = install_all(
            skills, root / harness.directory, force=force, docs_root=bundle.docs_source()
        )
        reports += [f"  {line}" for line in installed]

    # The checkout the package's source lives in states its own conventions, so it gets the root
    # names linked to them. A block there would describe this project to itself in words written
    # for somebody else's project.
    if bundle.is_source_checkout(root):
        return reports + link_instructions(root)

    return reports + [update_instructions(root / bundle.AGENTS_FILE, agents_block())]


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``yasuki-install-skills``.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments. Default None, meaning read them from ``sys.argv``.

    Returns
    -------
    status : int
        Process exit status. Zero on success.
    """
    args = _build_parser().parse_args(argv)

    skills = bundle.available_skills()

    if not skills:
        print(f"No skills found in {bundle.SKILLS_SOURCE}", file=sys.stderr)
        return 1

    if args.list:
        for skill in skills:
            print(skill.name)
        return 0

    interactive = sys.stdin.isatty()
    names = args.harness or (ask() if interactive else [])

    if not names:
        print(
            "Nothing installed."
            if interactive
            else "Nothing installed: pass --harness NAME (repeatable) to say which agent's "
            "directory to write. Run with a terminal attached to be asked instead.",
            file=sys.stderr,
        )
        return 1

    for line in install(Path.cwd(), skills, chosen(names), force=args.force):
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
