import ast
import pathlib

import yasuki_gui

ENTRY_POINT = pathlib.Path(yasuki_gui.__file__).parent / "__main__.py"


def _functions() -> dict[str, ast.FunctionDef]:
    """Every function the entry point defines at module level, by name."""
    module = ast.parse(ENTRY_POINT.read_text(encoding="utf-8"))
    return {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}


def test_the_entry_point_defines_nothing_but_building_and_running():
    """What the refactor was for. Every other responsibility has an owner — the host, the window,
    the presenter — so a new function here is a fourth one accreting where the last tangle grew."""
    assert set(_functions()) == {"build_client", "main"}


def test_nothing_is_defined_inside_the_builder():
    """A nested function closes over whatever is in scope, which is how the original grew to
    nineteen of them sharing state no signature named."""
    nested = [
        getattr(node, "name", "<lambda>")
        for statement in _functions()["build_client"].body
        for node in ast.walk(statement)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda)
    ]

    assert nested == []


def test_main_only_builds_and_runs():
    """Two statements would already be one too many: whatever a second one did would be startup
    work that belongs to a collaborator."""
    body = _functions()["main"].body

    assert len(body) == 1
    assert isinstance(body[0], ast.Expr)
