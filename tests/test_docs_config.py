import ast
import importlib
import pathlib

CONF = pathlib.Path("docs/conf.py")


def xref_aliases() -> dict[str, str]:
    """The docstring type names ``conf.py`` maps to a full path, read without importing Sphinx."""
    for node in ast.parse(CONF.read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if any(isinstance(t, ast.Name) and t.id == "numpydoc_xref_aliases" for t in targets):
            return ast.literal_eval(node.value)
    raise AssertionError("numpydoc_xref_aliases is not a plain assignment in docs/conf.py")


def _resolves(path: str) -> bool:
    module, _, attribute = path.rpartition(".")
    try:
        return hasattr(importlib.import_module(module), attribute)
    except ModuleNotFoundError:
        return False


def test_every_docstring_type_alias_names_something_that_exists():
    # numpydoc_xref_param_type turns each bare type name in a Parameters block into a reference, so
    # these are what make `agent : Agent` a link. An alias pointing at a module that has moved
    # resolves to nothing rather than failing the build, so the docs quietly lose the links and the
    # rename that broke them looks clean.
    aliases = xref_aliases()

    assert len(aliases) > 5  # a dict read as empty would satisfy the check below vacuously
    assert (
        sorted(f"{name} -> {path}" for name, path in aliases.items() if not _resolves(path)) == []
    )
