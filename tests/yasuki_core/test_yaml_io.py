import ast
import pathlib

import pytest
import yaml

import yasuki_core
from yasuki_core import yaml_io

# Derived from the imported package rather than counted back from this file: a test moved to
# another directory would otherwise scan the wrong tree and pass without reading a line.
SRC = pathlib.Path(yasuki_core.__file__).parent.parent


@pytest.mark.skipif(
    not hasattr(yaml, "CSafeLoader"), reason="this PyYAML was built without libyaml"
)
def test_the_compiled_scanner_is_used_where_pyyaml_provides_one():
    """Reading the committed card data is almost entirely YAML scanning, and the C scanner does it
    about nine times faster — so which loader this module picks is the whole reason it exists."""
    assert yaml_io.SafeLoader is yaml.CSafeLoader


def test_no_module_reaches_for_safe_load():
    """``yaml.safe_load`` hardcodes the pure-Python scanner whatever PyYAML was built with, so a
    call site drifting back to it costs the speed silently — no other test would fail.

    Read as syntax rather than as text: this file and :mod:`yasuki_core.yaml_io` both name the
    function in prose, and a substring search would report them.
    """
    offenders = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path in SRC.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and node.attr == "safe_load"
        and isinstance(node.value, ast.Name)
        and node.value.id == "yaml"
    ]

    assert offenders == []


def test_the_module_scan_reads_the_source_tree():
    # Guards the check above: a scan that walked the wrong tree finds no offenders and passes.
    assert len(list(SRC.rglob("*.py"))) > 50
