from pathlib import Path

from yasuki_skills.bundle import PACKAGE_ROOT

BLOCK_SOURCE = PACKAGE_ROOT / "agents_block.md"

# The installer owns what sits between these and nothing else in the file. Both must be present,
# in order, for the block to be replaced.
BLOCK_START = "<!-- BEGIN game-on-yasuki -->"

BLOCK_END = "<!-- END game-on-yasuki -->"


def agents_block() -> str:
    """Return the block the installer owns inside an instruction file, markers included."""
    return BLOCK_SOURCE.read_text(encoding="utf-8")


def _blank_line_before(body: str) -> str:
    """Return the newlines needed to leave exactly one blank line after ``body``."""
    if not body or body.endswith("\n\n"):
        return ""

    if body.endswith("\n"):
        return "\n"

    return "\n\n"


def update_instructions(path: Path, block: str) -> str:
    """Write the owned block into ``path``, leaving every other line of it alone.

    The block is appended when the file has no markers and replaced in place when it has exactly
    one pair. Anything else is left untouched and reported: unbalanced markers and repeated blocks
    cannot be resolved without guessing which text is current, a symlink would send the edit to a
    file somewhere else entirely, and none of these is the installer's to overwrite.

    Parameters
    ----------
    path : Path
        The instruction file to update. Created if absent.
    block : str
        The block to write, as :func:`agents_block` returns.

    Returns
    -------
    report : str
        One line saying what happened, for printing.
    """
    # Writing through a symlink edits whatever it points at -- in a checkout, that is this
    # package's own instruction file.
    if path.is_symlink():
        return f"skip     {path.name}  (a symlink; left alone)"

    if path.is_dir():
        return f"skip     {path.name}  (a directory is already there)"

    body = path.read_text(encoding="utf-8") if path.is_file() else ""

    start = body.find(BLOCK_START)
    end = body.find(BLOCK_END)

    if body.count(BLOCK_START) != body.count(BLOCK_END) or start > end:
        return f"skip     {path.name}  (markers are unbalanced; left alone)"

    if body.count(BLOCK_START) > 1:
        return f"skip     {path.name}  (more than one block; left alone)"

    if start == -1:
        path.write_text(body + _blank_line_before(body) + block, encoding="utf-8")

        return f"update   {path.name}  (block appended)"

    path.write_text(
        body[:start] + block.rstrip("\n") + body[end + len(BLOCK_END) :], encoding="utf-8"
    )

    return f"update   {path.name}  (block replaced)"
