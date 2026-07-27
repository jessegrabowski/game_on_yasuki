import importlib
import inspect
import pkgutil
import shutil
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
        f".. automodule:: {module_name}",
        "",
        f".. currentmodule:: {module_name}",
        "",
    ]
    for rubric, names, toctree in (
        ("Classes", classes, True),
        ("Functions", functions, True),
        ("Re-exported", reexported, False),
    ):
        if not names:
            continue
        lines += [f".. rubric:: {rubric}", "", ".. autosummary::"]
        if toctree:
            lines.append("    :toctree: generated/")
        lines.append("")
        lines += [f"    {name}" for name in names]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    if API_DIR.exists():
        shutil.rmtree(API_DIR)
    API_DIR.mkdir(parents=True)

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
            (API_DIR / f"{module_name}.rst").write_text(rst_for_module(module_name, *members))
            package_pages[pkg].append(module_name)

    for pkg, modules in package_pages.items():
        body = rst_for_module(pkg, *public_members(importlib.import_module(pkg)))
        toc = ["", ".. rubric:: Submodules", "", ".. toctree::", "    :maxdepth: 1", ""]
        toc += [f"    {name} <{name}>" for name in sorted(modules)]
        (API_DIR / f"{pkg}.rst").write_text(body + "\n".join(toc) + "\n")

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
    (API_DIR / "index.rst").write_text("\n".join(index) + "\n")

    written = sum(len(m) for m in package_pages.values()) + len(PACKAGES)
    print(f"Wrote {written} module pages under {API_DIR}")
    if failures:
        print(f"\n{len(failures)} module(s) failed to import:")
        for name, err in failures:
            print(f"  - {name}: {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
