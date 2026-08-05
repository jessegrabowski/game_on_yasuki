import ast
import pathlib

import yasuki_core

CORE = pathlib.Path(yasuki_core.__file__).parent
# yasuki_core is the substrate the other two packages sit on. It may not import either of them, or
# the dependency runs both ways and neither can be used without the other.
FORBIDDEN = ("yasuki_web", "yasuki_gui")


def _imported_modules(source: pathlib.Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_core_imports_nothing_from_the_ui_packages():
    # Reports every offender at once: a back-edge is usually introduced by a move that touches
    # several files, and fixing them one failure at a time is needless.
    offending = [
        f"{source.relative_to(CORE)} imports {name}"
        for source in sorted(CORE.rglob("*.py"))
        for name in sorted(_imported_modules(source))
        if name.split(".")[0] in FORBIDDEN
    ]

    assert offending == []


def test_the_scan_can_see_an_offending_import(tmp_path):
    # Guards the test above: a scanner that found nothing would pass it vacuously.
    probe = tmp_path / "probe.py"
    probe.write_text("from yasuki_gui.session import build_demo_state\nimport yasuki_web.main\n")

    found = {name.split(".")[0] for name in _imported_modules(probe)}

    assert found >= set(FORBIDDEN)
