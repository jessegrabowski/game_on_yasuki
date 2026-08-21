import ast
import collections
import datetime
import functools
import pathlib
import re
import typing

import yaml

from yasuki_core import DATABASE_DIR
from yasuki_core.engine.rules import cards
from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries
from yasuki_core.install.yaml_to_sql import card_slug

CARDS_DIR = pathlib.Path(cards.__file__).parent
DEFAULT_SET_INFO_PATH = DATABASE_DIR / "set_info.yaml"
HEADER = re.compile(r"^# --- (.+) ---$", re.M)
# Sorts after every real release date, so a set with no recorded date never wins a first-printing
# comparison against one that has.
UNDATED = datetime.date(9999, 1, 1)

# Registrations that name a card id, by the form they take. Choice resolvers are absent: they key on
# the name of a step in a sequence rather than on a card, so they carry no id to place or order.
_DECORATORS = {
    "on",
    "gold_handler",
    "recruit_discount",
    "invest_discount",
    "keyword_grant",
    "attachment_grant",
    "attach_restriction",
}
_CALLS = {
    "register_ability",
    "register_invest",
    "register_production_boost",
    "may_remain_bowed",
}


class CardFunction(typing.NamedTuple):
    """A function a card module defines, and what the module does with it.

    Attributes
    ----------
    card_id : str
        The card whose section header the definition sits under.
    name : str
        The function's name.
    resolves : str or None
        The choice the function is registered to resolve, or None when it resolves none.
    registered : bool
        Whether the module puts the function to work as a handler, as against calling it from one.
    """

    card_id: str
    name: str
    resolves: str | None
    registered: bool


def card_modules() -> list[pathlib.Path]:
    return sorted(path for path in CARDS_DIR.glob("*.py") if path.name != "__init__.py")


@functools.cache
def registered_ids(module: pathlib.Path) -> tuple[str, ...]:
    """The card ids ``module`` registers a handler for, in source order and with repeats."""
    ids = []
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _DECORATORS or node.func.id in _CALLS:
                # @on(Event, "id") puts the id last; every other form puts it first.
                argument = node.args[-1] if node.func.id == "on" else node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    ids.append(argument.value)
    return tuple(ids)


def _sections(source: str) -> list[tuple[int, str]]:
    """Each ``(line number, card id)`` a section header declares, in source order."""
    return [
        (number, card_slug(match.group(1)))
        for number, line in enumerate(source.splitlines(), start=1)
        if (match := HEADER.match(line))
    ]


def _owning_card(sections: list[tuple[int, str]], line: int) -> str | None:
    """The card whose section ``line`` falls in, or None for a line ahead of the first header."""
    owning = [card_id for start, card_id in sections if start <= line]
    return owning[-1] if owning else None


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, which is how a card names the token it makes."""
    return {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
        for target in node.targets
        if isinstance(target, ast.Name) and isinstance(node.value.value, str)
    }


def _token_references(tree: ast.Module, constants: dict[str, str]) -> list[tuple[int, str]]:
    """Each ``(line, token id)`` the source names: the template a ``CreateToken`` stamps from, and
    the template a targets function looks up to judge before the card exists."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        argument = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "CreateToken" and node.args:
                argument = node.args[0]
        elif isinstance(node, ast.Subscript):
            looked_up = node.value
            if isinstance(looked_up, ast.Attribute) and looked_up.attr == "creatable_tokens":
                argument = node.slice
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            found.append((node.lineno, argument.value))
        elif isinstance(argument, ast.Name) and argument.id in constants:
            found.append((node.lineno, constants[argument.id]))
    return found


@functools.cache
def created_tokens(module: pathlib.Path) -> tuple[tuple[str, str], ...]:
    """Each ``(card id, token id)`` the module names, attributed to the card whose section names it.

    A card's tokens are read off its own block, so a token named under the wrong header is a card
    creating something the database says it cannot.
    """
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sections = _sections(source)
    pairs = set()
    for line, token in _token_references(tree, _module_constants(tree)):
        owning = _owning_card(sections, line)
        if owning is not None:
            pairs.add((owning, token))
    return tuple(sorted(pairs))


# The calls that put a function to work as a card's handler. A name reaching one of these is
# registered; a name that never does is a helper the card's own handlers call.
_REGISTRARS = {
    "on",
    "register_ability",
    "register_invest",
    "register_production_boost",
    "Ability",
    "InvestAbility",
    "ProductionBoost",
}


@functools.cache
def card_functions(module: pathlib.Path) -> tuple[CardFunction, ...]:
    """Every module-level function the module defines under a card's section header.

    A function defined ahead of the first header belongs to no card and is left out.
    """
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sections = _sections(source)
    registered = _registered_names(tree)
    found = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        owning = _owning_card(sections, node.lineno)
        if owning is None:
            continue
        resolves = _resolver_key(node)
        handler = (
            resolves is not None or node.name in registered or _has_registering_decorator(node)
        )
        found.append(CardFunction(owning, node.name, resolves, handler))
    return tuple(found)


def _registered_names(tree: ast.Module) -> set[str]:
    """The functions handed to a registration call, including the ``on(...)(handler)`` form."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        registering = isinstance(called, ast.Name) and called.id in _REGISTRARS
        # on(Event, "id")(handler) registers by calling what on() returned.
        chained = (
            isinstance(called, ast.Call)
            and isinstance(called.func, ast.Name)
            and called.func.id in _REGISTRARS
        )
        if not (registering or chained):
            continue
        arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
        names.update(item.id for item in arguments if isinstance(item, ast.Name))
    return names


def _has_registering_decorator(node: ast.FunctionDef) -> bool:
    return any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Name)
        and decorator.func.id in _DECORATORS
        for decorator in node.decorator_list
    )


def _resolver_key(node: ast.FunctionDef) -> str | None:
    """The choice ``node`` is registered to resolve, or None when it resolves none."""
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name)
            and decorator.func.id == "choice_resolver"
            and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        ):
            return decorator.args[0].value
    return None


@functools.cache
def headers(module: pathlib.Path) -> tuple[str, ...]:
    """The card titles ``module`` declares section headers for, in source order."""
    return tuple(HEADER.findall(module.read_text(encoding="utf-8")))


def first_printing_module(
    cards_dir: pathlib.Path = DEFAULT_CARDS_PATH,
    set_info_path: pathlib.Path = DEFAULT_SET_INFO_PATH,
) -> dict[str, str]:
    """
    The module name each card id belongs in: the file stem of its earliest-released set.

    A reprinted card is implemented once, in its first printing, so its module is decided by release
    date. Two sets sharing a date break on file stem, and undated sets sort last, so the answer is
    the same on every machine and for every card.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    set_info_path : path, optional
        The arc-grouped set metadata carrying each set's release date. Default is the packaged
        ``set_info.yaml``.

    Returns
    -------
    dict mapping str to str
        Card id to the module stem it belongs in.
    """
    metadata = yaml.safe_load(set_info_path.read_text(encoding="utf-8"))
    released = {
        entry["set_name"]: entry.get("release_date") or UNDATED
        for arc in metadata["arcs"]
        for entry in arc["sets"]
    }

    printings = collections.defaultdict(set)
    for entry in iter_set_entries(cards_dir):
        printings[entry.card_id].add((released.get(entry.set_name, UNDATED), entry.source.stem))
    return {card_id: min(dated)[1] for card_id, dated in printings.items()}
