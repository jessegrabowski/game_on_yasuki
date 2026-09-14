import pathlib
import re
import sys

CLEAR = re.compile(r"^\s*game\.pending = None\b", re.M)

DECISION_LAYER = "src/yasuki_core/engine/rules/turn/action_sequence.py"


def clears_outside_the_decision_layer(path: pathlib.Path, text: str) -> list[int]:
    """Return the line numbers at which ``text`` clears ``game.pending``, unless ``path`` is the
    decision layer, whose ``submit`` and ``cancel`` own the clear."""
    if path.as_posix().endswith(DECISION_LAYER):
        return []
    return [text.count("\n", 0, match.start()) + 1 for match in CLEAR.finditer(text)]


def main(argv: list[str] | None = None) -> int:
    """Report every ``game.pending = None`` outside the decision layer.

    A handler that clears the request itself decides its own moment for it, and the moment is the
    bug: the request a trigger raises during the handler is the one that has to survive.

    Parameters
    ----------
    argv : list of str, optional
        The files to check, as pre-commit passes them. Default None, meaning ``sys.argv[1:]``.

    Returns
    -------
    status : int
        Zero when no file outside the decision layer clears the request.
    """
    argv = sys.argv[1:] if argv is None else argv

    failed = 0
    for name in argv:
        path = pathlib.Path(name)

        for line in clears_outside_the_decision_layer(path, path.read_text(encoding="utf-8")):
            print(f"{path}:{line}: clears game.pending; only submit and cancel may")
            failed = 1

    return failed


if __name__ == "__main__":
    sys.exit(main())
