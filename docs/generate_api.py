import importlib
import inspect
import pkgutil
import sys
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parent
API_DIR = DOCS_DIR / "api"
sys.path.insert(0, str(DOCS_DIR.parent / "src"))

PACKAGES = ["yasuki_core", "yasuki_web", "yasuki_gui"]
SKIP_SUFFIXES = ("._version", ".__main__")
SKIP_CONTAINS = (".migrations",)


def iter_modules(package_name: str, on_error) -> list[str]:
    package = importlib.import_module(package_name)
    names = [package_name]
    for info in pkgutil.walk_packages(package.__path__, f"{package_name}.", onerror=on_error):
        name = info.name
        if name.endswith(SKIP_SUFFIXES) or any(part in name for part in SKIP_CONTAINS):
            continue
        names.append(name)
    return names


def member_kind(obj) -> str | None:
    if inspect.isclass(obj):
        return "class"
    if inspect.isfunction(inspect.unwrap(obj)):
        return "function"
    return None


def public_members(module) -> tuple[list[str], list[str], list[str]]:
    exported = set(getattr(module, "__all__", []))
    classes, functions, reexported = [], [], []
    for name, obj in vars(module).items():
        if name.startswith("_"):
            continue
        own = getattr(obj, "__module__", None) == module.__name__
        if not (own or name in exported):
            continue
        kind = member_kind(obj)
        if kind is None:
            continue
        if own:
            (classes if kind == "class" else functions).append(name)
        else:
            # Re-exported from another module: link to its canonical page rather
            # than generating a second stub. The path is relative to this module
            # (the page's currentmodule) so autosummary resolves it there.
            canonical = f"{obj.__module__}.{name}"
            prefix = f"{module.__name__}."
            reexported.append(canonical.removeprefix(prefix))
    return sorted(classes), sorted(functions), sorted(reexported)


def rst_for_module(module_name: str, classes, functions, reexported=()) -> str:
    lines = [
        module_name,
        "=" * len(module_name),
        "",
        f".. currentmodule:: {module_name}",
        "",
    ]
    for rubric, names in (
        ("Classes", classes),
        ("Functions", functions),
        ("Re-exported", reexported),
    ):
        if not names:
            continue
        lines += [f".. rubric:: {rubric}", "", ".. autosummary::", ""]
        lines += [f"    {name}" for name in names]
        lines.append("")
    # The members are documented here rather than on a page each: one page per module builds in a
    # fraction of the time and still anchors every class, method and function for deep linking.
    # undoc-members keeps a member without its own docstring from vanishing.
    lines += [
        f".. automodule:: {module_name}",
        "    :members:",
        "    :undoc-members:",
        "",
    ]
    return "\n".join(lines)


def write_if_changed(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` only when it differs from what is already there.

    Rewriting an identical page still bumps its mtime, which Sphinx reads as a change and rebuilds
    every page that references it — turning an incremental build back into a full one.
    """
    if path.exists() and path.read_text() == text:
        return
    path.write_text(text)


def resolves(dotted: str) -> bool:
    """Whether ``dotted`` still names something importable."""
    parts = dotted.split(".")
    for split in range(len(parts), 0, -1):
        try:
            obj = importlib.import_module(".".join(parts[:split]))
        except Exception:  # noqa: BLE001 - any import failure means it is gone
            continue
        for attr in parts[split:]:
            obj = getattr(obj, attr, None)
            if obj is None:
                return False
        return True
    return False


def prune_stale_stubs() -> int:
    """Delete autosummary stubs whose target no longer exists, and report how many went.

    Sphinx reads every ``.rst`` under ``docs/``, so a stub left behind by a deleted symbol fails the
    build rather than being ignored. They are gitignored build output, which is what lets them
    survive a branch switch long enough to cause that. The stubs come from the hand-written
    vocabulary pages, which name their classes explicitly.
    """
    generated = API_DIR / "generated"
    if not generated.exists():
        return 0
    removed = 0
    for stub in generated.rglob("*.rst"):
        if not resolves(stub.stem):
            stub.unlink()
            removed += 1
    return removed


def main() -> int:
    API_DIR.mkdir(parents=True, exist_ok=True)
    stale = {path for path in API_DIR.glob("*.rst")}

    failures: list[tuple[str, str]] = []

    def on_walk_error(name: str) -> None:
        exc = sys.exc_info()[1]
        failures.append((name, f"{type(exc).__name__}: {exc}"))

    package_pages: dict[str, list[str]] = {pkg: [] for pkg in PACKAGES}

    for pkg in PACKAGES:
        for module_name in iter_modules(pkg, on_walk_error):
            if module_name == pkg:
                continue  # the package's own page is written below, with its toctree
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 - report, don't abort the sweep
                failures.append((module_name, f"{type(exc).__name__}: {exc}"))
                continue
            members = public_members(module)
            if not any(members):
                continue
            page = API_DIR / f"{module_name}.rst"
            write_if_changed(page, rst_for_module(module_name, *members))
            stale.discard(page)
            package_pages[pkg].append(module_name)

    for pkg, modules in package_pages.items():
        body = rst_for_module(pkg, *public_members(importlib.import_module(pkg)))
        toc = ["", ".. rubric:: Submodules", "", ".. toctree::", "    :maxdepth: 1", ""]
        toc += [f"    {name} <{name}>" for name in sorted(modules)]
        page = API_DIR / f"{pkg}.rst"
        write_if_changed(page, body + "\n".join(toc) + "\n")
        stale.discard(page)

    index = [
        "API Reference",
        "=============",
        "",
        "Auto-generated reference for the three packages.",
        "",
        ".. toctree::",
        "    :maxdepth: 2",
        "",
    ]
    index += [f"    {pkg} <{pkg}>" for pkg in PACKAGES]
    index_page = API_DIR / "index.rst"
    write_if_changed(index_page, "\n".join(index) + "\n")
    stale.discard(index_page)

    # A module that has gone away leaves a page behind; autosummary's own stubs under generated/
    # are Sphinx's to manage and are left alone.
    for page in stale:
        page.unlink()

    written = sum(len(m) for m in package_pages.values()) + len(PACKAGES)
    pruned = prune_stale_stubs()
    print(f"Wrote {written} module pages under {API_DIR}")
    if pruned:
        print(f"Pruned {pruned} stale autosummary stub(s)")
    if failures:
        print(f"\n{len(failures)} module(s) failed to import:")
        for name, err in failures:
            print(f"  - {name}: {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
