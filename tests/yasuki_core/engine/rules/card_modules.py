import ast
import collections
import datetime
import functools
import pathlib
import re

import yaml

from yasuki_core import DATABASE_DIR
from yasuki_core.engine.rules import cards
from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries

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
    "keyword_grant",
    "attachment_grant",
    "attach_restriction",
    "province_strength_grant",
}
_CALLS = {"register_ability", "register_invest", "register_production_boost"}


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
