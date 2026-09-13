import ast
import pathlib
import re
import sys
import typing


def card_slug(text: str) -> str:
    """A card title as its id. Duplicated from ``yasuki_core.install.yaml_to_sql.card_slug``, which
    is the source of truth: this runs as a pre-commit hook with no project environment, and a
    divergence shows up here as a header matching no registration rather than as bad data."""
    lowered = text.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


HEADER = re.compile(r"^# --- (.+) ---$", re.M)


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
    "attack_strength_against",
    "favor_payer",
    "lobby_bar",
    "lobby_bonus_grant",
    "province_strength_grant",
}


_CALLS = {
    "register_ability",
    "register_edict",
    "register_event_entry",
    "register_enters_unbowed",
    "register_invest",
    "register_may_not_lobby",
    "register_may_remain_bowed",
    "register_bow_waiver",
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


def registered_ids(module: pathlib.Path) -> tuple[str, ...]:
    """The card ids ``module`` registers a handler for, in source order and with repeats.

    Sorted by position rather than taken in walk order: ``ast.walk`` is breadth-first, so a bare
    ``register_ability(...)`` statement is reached before a decorator further up the file, and the
    ids would come back interleaved by nesting depth instead of by line.
    """
    found = []
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _DECORATORS or node.func.id in _CALLS:
                # @on(Event, "id") puts the id last; every other form puts it first.
                argument = node.args[-1] if node.func.id == "on" else node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.append((argument.lineno, argument.col_offset, argument.value))
    return tuple(value for _, _, value in sorted(found))


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


# The calls that put a function to work as a card's handler. A name reaching one of these is
# registered; a name that never does is a helper the card's own handlers call.
_REGISTRARS = {
    "on",
    "register_ability",
    "register_invest",
    "register_self_grant",
    "Ability",
    "InvestAbility",
}


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


def ability_keys(module: pathlib.Path) -> frozenset[str]:
    """Every ``key`` the module names on an :class:`Ability`, which is how a card printing several
    tells them apart."""
    found = set()
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id != "Ability":
            continue
        for keyword in node.keywords:
            if keyword.arg == "key" and isinstance(keyword.value, ast.Constant):
                found.add(keyword.value.value)
    return frozenset(found)


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
            and isinstance(decorator.args[0].value, str)
        ):
            return decorator.args[0].value
    return None


def headers(module: pathlib.Path) -> tuple[str, ...]:
    """The card titles ``module`` declares section headers for, in source order."""
    return tuple(HEADER.findall(module.read_text(encoding="utf-8")))


# The jobs a card's handler can hold, spelled the way its name has to end. A handler's name is its
# card's id and one of these, so a card's whole implementation answers a grep for its id and every
# function of a kind answers a grep for its role. A card printing several abilities qualifies the
# role with that ability's key, as in ``_incendiary_archers_fear_effects``, since one name per
# role would collide between them.
ROLES = frozenset(
    {
        # the three parts of an activated ability
        "cost",
        "targets",
        "effects",
        # the per-registry hooks
        "invest",
        "gold",
        "recruit_discount",
        "invest_discount",
        "keywords",
        "attachment_grant",
        "attach_restriction",
        "attack_strength",
        "province_strength",
        "lobby_bonus",
        "favor_payer",
        "lobby_bar",
        # triggers, named for the event they answer
        "producing_gold",
        "produced_gold",
        "entered_play",
        "destroyed",
        "straightened",
        "turn_started",
        "counter_gained",
        "card_discarded",
        "entered_play_or_destroyed",
    }
)


def _named_conventionally(function: CardFunction, keys: frozenset[str]) -> bool:
    """A resolver is named for the choice it resolves, a handler for its card and its role, and a
    helper only has to carry its card's id. ``keys`` are the ability keys the module registers, each
    of which may qualify a role."""
    if function.resolves is not None:
        return function.name == f"_resolve_{function.resolves}"
    prefix = f"_{function.card_id}_"
    if not function.name.startswith(prefix):
        return False
    if not function.registered:
        return True
    suffix = function.name.removeprefix(prefix)
    qualified = {f"{key}_{role}" for key in keys for role in ROLES}
    return suffix in ROLES or suffix in qualified


def _out_of_order(module: pathlib.Path) -> list[str]:
    ids = list(dict.fromkeys(registered_ids(module)))
    pairs = zip(ids, ids[1:], strict=False)
    return [f"{later} follows {earlier}" for earlier, later in pairs if later < earlier]


def _split_headers(module: pathlib.Path) -> list[str]:
    seen, repeated = set(), []
    for line, card_id in _sections(module.read_text(encoding="utf-8")):
        if card_id in seen:
            repeated.append(f"line {line}: a second header for {card_id}")
        seen.add(card_id)
    return repeated


def _header_mismatch(module: pathlib.Path) -> list[str]:
    sectioned = _sections(module.read_text(encoding="utf-8"))
    registered = list(dict.fromkeys(registered_ids(module)))
    return [
        f"line {line}: the header names {card_id}, the block registers {beneath}"
        for (line, card_id), beneath in zip(sectioned, registered, strict=False)
        if card_id != beneath
    ]


def _interleaved(module: pathlib.Path) -> list[str]:
    ids = registered_ids(module)
    runs = [card_id for index, card_id in enumerate(ids) if index == 0 or ids[index - 1] != card_id]
    return [
        f"{card_id} is registered in {runs.count(card_id)} separate runs"
        for card_id in dict.fromkeys(runs)
        if runs.count(card_id) > 1
    ]


def _misnamed(module: pathlib.Path) -> list[str]:
    keys = ability_keys(module)
    return [
        f"{function.name} should start with _{function.card_id}_"
        for function in card_functions(module)
        if not _named_conventionally(function, keys)
    ]


CHECKS = (
    ("cards are not in alphabetical order", _out_of_order),
    ("a card has a second header", _split_headers),
    ("a header does not name the card beneath it", _header_mismatch),
    ("a card's registrations are interleaved with another's", _interleaved),
    ("a handler is not named for its card and its job", _misnamed),
)


def main(argv: list[str]) -> int:
    problems = [
        f"{path}: {label}: {detail}"
        for path in argv
        for label, check in CHECKS
        for detail in check(pathlib.Path(path))
    ]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
