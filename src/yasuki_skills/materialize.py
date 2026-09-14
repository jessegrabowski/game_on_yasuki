import ast
import os
import re

from pathlib import Path
from typing import NamedTuple

DOCS_URL = "https://game-on-yasuki.readthedocs.io/en/latest/"

FENCE = re.compile(r"^```\{(?P<name>[a-z-]+)\}(?P<argument>.*)$")

OPTION = re.compile(r"^:(?P<key>[a-z-]+):(?P<value>.*)$")

# The role must not be preceded by a backtick, or a URL template inside code -- the web API's
# ``/api/cards/random/{count}`` -- reads as one and loses its braces.
ROLE = re.compile(r"(?<!`)\{(?P<role>func|class|meth|attr|mod|card)\}`(?P<target>[^`]+)`")

LINK = re.compile(r"\]\((?P<target>[^)#]+\.md)(?P<anchor>#[^)]*)?\)")

INCLUDE_OPTIONS = frozenset(
    {"language", "pyobject", "start-at", "start-after", "end-at", "end-before", "dedent"}
)


class MaterializeError(RuntimeError):
    """A page could not be rendered for a skill, naming the page and what did not resolve."""


class Block(NamedTuple):
    """One fenced directive, as its options and the lines between the fences."""

    options: dict[str, str]
    body: list[str]


def materialize(page: Path, docs_root: Path, source_root: Path, installed: set[str]) -> str:
    """Render one documentation page as plain markdown an agent can read.

    Every directive is resolved against the current source or dropped, and every cross-reference
    role becomes the text it stands for.

    Parameters
    ----------
    page : Path
        The page to render.
    docs_root : Path
        Root of the documentation tree, used to state paths the way a manifest does.
    source_root : Path
        Directory the included source files are resolved against when the page's own relative
        path does not reach them, as in an installed package where there is no ``src/``.
    installed : set of str
        Docs-relative paths of the pages this skill carries. A link to another page of the
        documentation is rewritten to the hosted site; a link out of the tree is left as written.

    Returns
    -------
    body : str
        The rendered page.

    Raises
    ------
    MaterializeError
        If a directive, an option, or an include target does not resolve.
    """
    lines = page.read_text(encoding="utf-8").splitlines()
    rendered: list[str] = []

    index = 0
    while index < len(lines):
        fence = FENCE.match(lines[index])

        if fence is None:
            rendered.append(_inline(lines[index], page, docs_root, installed))
            index += 1
            continue

        block, index = _read_block(lines, index)
        rendered.extend(_render(fence["name"], fence["argument"].strip(), block, page, source_root))

    return "\n".join(rendered).rstrip("\n") + "\n"


def _read_block(lines: list[str], index: int) -> tuple[Block, int]:
    """Read one fenced directive, returning it and the index of the line after it."""
    options: dict[str, str] = {}
    body: list[str] = []

    index += 1
    while index < len(lines) and (option := OPTION.match(lines[index])):
        options[option.group("key")] = option.group("value").strip()
        index += 1

    while index < len(lines) and lines[index] != "```":
        body.append(lines[index])
        index += 1

    return Block(options, body), index + 1


def _render(name: str, argument: str, block: Block, page: Path, source_root: Path) -> list[str]:
    """Render one directive to the lines that replace it."""
    options, body = block

    if name == "literalinclude":
        return _include(argument, options, page, source_root)

    if name == "eval-rst":
        return _autosummary(body)

    if name == "card-image":
        printing = options.get("printing")
        shown = f"{argument} ({printing})" if printing else argument

        return [f"*Card image: {shown}.*"]

    if name == "toctree":
        return []

    if name in {"note", "warning", "tip"}:
        return [f"**{name.title()}:** " + " ".join(line.strip() for line in body if line.strip())]

    raise MaterializeError(f"{page}: no rule for the '{name}' directive")


def _include(argument: str, options: dict[str, str], page: Path, source_root: Path) -> list[str]:
    """Resolve a ``literalinclude`` to the source text it names."""
    unsupported = set(options) - INCLUDE_OPTIONS
    if unsupported:
        raise MaterializeError(
            f"{page}: literalinclude of {argument} uses {', '.join(sorted(unsupported))}, "
            "which this renderer does not resolve"
        )

    target = _resolve(argument, page, source_root)
    text = target.read_text(encoding="utf-8")

    if "pyobject" in options:
        excerpt = _pyobject(text, options["pyobject"], target, page)
    else:
        excerpt = _slice(text.splitlines(), options, target, page)

    if "dedent" in options:
        width = int(options["dedent"])
        excerpt = [line[width:] if line[:width].isspace() else line.lstrip() for line in excerpt]

    return [f"```{options.get('language', '')}", *excerpt, "```"]


def _resolve(argument: str, page: Path, source_root: Path) -> Path:
    """Locate an included file, from the repository tree or from an installed package."""
    beside = Path(os.path.normpath(page.parent / argument))
    if beside.is_file():
        return beside

    parts = Path(argument).parts
    if "src" in parts:
        packaged = source_root.joinpath(*parts[parts.index("src") + 1 :])
        if packaged.is_file():
            return packaged

    raise MaterializeError(f"{page}: includes {argument}, which is not there")


def _pyobject(text: str, name: str, target: Path, page: Path) -> list[str]:
    """Return the source of one top-level function or class, decorators included."""
    for node in ast.parse(text).body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue

        if node.name != name:
            continue

        first = node.decorator_list[0].lineno if node.decorator_list else node.lineno

        return text.splitlines()[first - 1 : node.end_lineno]

    raise MaterializeError(f"{page}: {target.name} has no '{name}' to include")


def _slice(lines: list[str], options: dict[str, str], target: Path, page: Path) -> list[str]:
    """Return the lines between the ``start`` and ``end`` markers, following Sphinx's bounds."""
    start = 0
    if "start-at" in options:
        start = _find(lines, _marker(options, "start-at", page), target, page)
    elif "start-after" in options:
        start = _find(lines, _marker(options, "start-after", page), target, page) + 1

    end = len(lines)
    if "end-at" in options:
        end = _find(lines[start:], _marker(options, "end-at", page), target, page) + start + 1
    elif "end-before" in options:
        end = _find(lines[start:], _marker(options, "end-before", page), target, page) + start

    return lines[start:end]


def _marker(options: dict[str, str], key: str, page: Path) -> str:
    """Return the text an option matches on, which has to be text."""
    marker = options[key]

    # A marker holding a "#" has to be quoted on the page, or MyST reads the rest as a comment.
    # Sphinx sees the text inside the quotes, and so must this.
    if len(marker) >= 2 and marker[0] == marker[-1] and marker[0] in "\"'":
        marker = marker[1:-1]

    if not marker:
        raise MaterializeError(f"{page}: its {key} names no text to match")

    return marker


def _find(lines: list[str], marker: str, target: Path, page: Path) -> int:
    """Return the index of the first line holding ``marker``."""
    for index, line in enumerate(lines):
        if marker in line:
            return index

    raise MaterializeError(f"{page}: {target.name} has no line holding '{marker}'")


def _autosummary(body: list[str]) -> list[str]:
    """Flatten an ``autosummary`` block to the names it lists, which are its whole content."""
    module = ""
    names = []

    for line in body:
        stripped = line.strip()

        if stripped.startswith(".. currentmodule::"):
            module = stripped.removeprefix(".. currentmodule::").strip()
        elif stripped and not stripped.startswith(".."):
            names.append(f"- ``{module}.{stripped}``" if module else f"- ``{stripped}``")

    return names


def _inline(line: str, page: Path, docs_root: Path, installed: set[str]) -> str:
    """Strip roles to their targets, and point links at pages that are actually there."""
    line = ROLE.sub(lambda match: _role(match), line)

    return LINK.sub(lambda match: _link(match, page, docs_root, installed), line)


def _role(match: re.Match[str]) -> str:
    """Render one cross-reference as the text Sphinx would show for it."""
    target = match.group("target")

    if match.group("role") == "card":
        return target

    # Sphinx shows only the last component of a target written with a leading tilde, and `.` is
    # its "search the current module" prefix. Both are addressing, not text.
    if target.startswith("~"):
        target = target.rsplit(".", 1)[-1]

    return f"``{target.lstrip('.')}``"


def _link(match: re.Match[str], page: Path, docs_root: Path, installed: set[str]) -> str:
    """Keep a link to an installed page relative; send the rest to the hosted documentation."""
    target = match.group("target")
    anchor = match.group("anchor") or ""
    resolved = Path(os.path.normpath(page.parent / target))

    try:
        relative = resolved.relative_to(docs_root).as_posix()
    except ValueError:
        # A link out of the documentation tree names a file in the repository, which the hosted
        # site does not serve either. Left as written.
        return match.group(0)

    if relative in installed:
        return f"]({target}{anchor})"

    return f"]({DOCS_URL}{relative.removesuffix('.md')}.html{anchor})"
