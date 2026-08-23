import ast
import inspect
from pathlib import Path

import yasuki_gui.__main__ as client


def _own_calls(function: ast.FunctionDef) -> set[str]:
    """The dotted names this function calls in its own body, ignoring the bodies of functions nested
    in it — those are separate paths with their own obligations."""
    nested = {
        node
        for child in function.body
        for node in ast.walk(child)
        if isinstance(node, ast.FunctionDef) and node is not function
    }
    inner = {node for parent in nested for node in ast.walk(parent)}
    return {
        ast.unparse(node.func)
        for child in function.body
        for node in ast.walk(child)
        if isinstance(node, ast.Call) and node not in inner
    }


def _functions() -> list[ast.FunctionDef]:
    tree = ast.parse(Path(inspect.getfile(client)).read_text())
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]


def test_every_path_that_starts_a_game_hands_over_to_the_opponent():
    """Starting a game whose first turn is the opponent's leaves the human with nothing to click, so
    a path that opens a session and only re-renders sits there forever. ``present_pending`` is what
    hands over, and it renders too, so a start path never wants a bare ``refresh``."""
    starters = [fn for fn in _functions() if "EngineSession.start" in _own_calls(fn)]

    assert starters, "no function opens an EngineSession; this guard is watching the wrong name"
    assert [fn.name for fn in starters if "present_pending" not in _own_calls(fn)] == []
