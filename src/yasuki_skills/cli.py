import argparse
import sys

from pathlib import Path

from yasuki_skills import bundle
from yasuki_skills.agents_file import agents_block, update_instructions
from yasuki_skills.harnesses import BY_NAME, HARNESSES, Harness
from yasuki_skills.install import install_all, link_instructions


def _build_parser() -> argparse.ArgumentParser:
    reads = "\n".join(
        f"  {harness.name:9} {harness.directory:18} {harness.reads}" for harness in HARNESSES
    )

    parser = argparse.ArgumentParser(
        prog="yasuki-install-skills",
        description=(
            "Install the game-on-yasuki agent skills into the current project. Skills follow the "
            "Agent Skills standard, so one copy serves every agent that implements it; the only "
            "difference between agents is which directory they read, and every one of them is "
            "written unless you narrow it with --harness.\n\n" + reads
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--harness",
        action="append",
        choices=sorted(BY_NAME),
        metavar="NAME",
        help="Write only this agent's directory. Repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Replace a skill that is already installed."
    )
    parser.add_argument("--list", action="store_true", help="List the bundled skills and exit.")

    return parser


def chosen(names: list[str] | None) -> list[Harness]:
    """Return the harnesses to install for, in declaration order.

    Parameters
    ----------
    names : list of str or None
        Names passed with ``--harness``, or None for every harness.

    Returns
    -------
    harnesses : list of Harness
        Those asked for, without repeats.
    """
    if not names:
        return list(HARNESSES)

    wanted = set(names)

    return [harness for harness in HARNESSES if harness.name in wanted]


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
        reports += [
            f"  {line}" for line in install_all(skills, root / harness.directory, force=force)
        ]

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

    for line in install(Path.cwd(), skills, chosen(args.harness), force=args.force):
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
