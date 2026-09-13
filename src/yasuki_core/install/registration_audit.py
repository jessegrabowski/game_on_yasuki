import ast
import difflib
import re
import sys
from pathlib import Path

from yasuki_core.engine.rules.abilities import registry
from yasuki_core.engine.rules import (
    state_based_actions,
    triggers,
)
from yasuki_core.engine.registrar import CARD_REGISTRIES

# The ability hints are keyed by printed id like every other per-card registry, so they are
# validated here even though a policy is not a rule. Imported for the registration it performs
# -- the registry catalogues itself when this module runs.
from yasuki_core import bots
from yasuki_core.bots import hints  # noqa: F401

# Without this the registries are empty and every check below passes vacuously.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.engine import rules
from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries, read_index


def registered_card_ids() -> dict[str, frozenset[str]]:
    """
    Every card id the engine keys a per-card handler on, grouped by the registry holding it.

    Every registry built through :mod:`~yasuki_core.engine.registrar` reports itself, so a new one
    is validated without being listed here. The three below are not built that way: two keep
    bespoke registration rules, and the triggers are keyed by event first.

    ``CHOICE_RESOLVERS`` is absent by design. It keys on the *kind* of a pending choice rather than
    on a card. ``modest_farm_straighten`` and ``sincerity_seed`` name steps in a sequence, not
    cards, so validating it against the card index would report failures that are not defects.
    """
    derived = {registry.label: frozenset(registry) for registry in CARD_REGISTRIES}
    return {
        **derived,
        "abilities": frozenset(registry._ABILITIES),
        "invest abilities": frozenset(registry._INVEST),
        "triggers": frozenset(
            card_id for by_card in triggers._TRIGGERS.values() for card_id in by_card
        ),
    }


def card_keyed_data() -> dict[str, frozenset[str]]:
    """Every card id the engine names as *data* rather than as a handler, grouped by the list
    holding it.

    Kept apart from :func:`~.registered_card_ids` because these ids do not live in a set module. A
    card excepted from a rulebook rule is a property of the card, listed beside the rule it excepts,
    and the layout scan would report every one of them as a registration it could not find. They are
    validated against the card index all the same.
    """
    return {"chi death exemptions": state_based_actions.CHI_DEATH_EXEMPT}


def duplicate_registrations(
    trigger_registry: dict[type, dict[str, list[triggers.Trigger]]] | None = None,
) -> list[str]:
    """
    One human-readable line per card id whose trigger is registered more than once.

    Only ``_TRIGGERS`` can hold a duplicate. It appends, so a handler copy-pasted into a second
    module fires the trigger twice, producing a wrong game state rather than a loud failure. Every
    other per-card registry raises on a repeated registration.

    Parameters
    ----------
    trigger_registry : dict mapping event type to a dict of card id to triggers, optional
        Defaults to the engine's own trigger registry.
    """
    if trigger_registry is None:
        trigger_registry = triggers._TRIGGERS

    problems = []
    for event_type, by_card in sorted(trigger_registry.items(), key=lambda item: item[0].__name__):
        for card_id, hooks in sorted(by_card.items()):
            names = [hook.__qualname__ for hook in hooks]
            repeated = sorted({name for name in names if names.count(name) > 1})
            for name in repeated:
                problems.append(
                    f"triggers: {card_id} registers {name} for {event_type.__name__} "
                    f"{names.count(name)} times"
                )
    return problems


def unregistered_card_ids(registries: dict[str, frozenset[str]] | None = None) -> list[str]:
    """
    One human-readable line per handler keyed on an id no card has, each with a nearest-match hint.

    A handler registered under a misspelled id never fires and never errors, so the card is silently
    dead. The hint is what turns that into a one-line fix: ``milet_farm`` reads as correct until
    something puts ``millet_farm`` beside it.

    Parameters
    ----------
    registries : dict mapping str to frozenset of str, optional
        Registry name to the card ids it keys on. Defaults to the engine's own registries.

    Returns
    -------
    list of str
        Sorted problem descriptions, empty when every registered id names a real card.
    """
    if registries is None:
        registries = registered_card_ids() | card_keyed_data()

    known = read_index()
    problems: list[str] = []
    for label, card_ids in sorted(registries.items()):
        for card_id in sorted(card_ids - known):
            closest = difflib.get_close_matches(card_id, known, n=1)
            hint = f". Did you mean {closest[0]}?" if closest else ""
            problems.append(f"{label}: no card has the id {card_id!r}{hint}")
    return problems


# The designator vocabulary the arc prints, as it reads on a card. Invest is deliberately absent: it
# is a recruit-time purchase registered in its own registry, not an activated ability.
_DESIGNATORS = (
    "Open",
    "Battle",
    "Dynasty",
    "Limited",
    "Reaction",
    "Interrupt",
    "Response",
    "Engage",
)
_QUALIFIERS = (
    r"(?:Absent|Kiho|Maho|Iaijutsu|Ninja|Economic|Repeatable|Tireless|Political"
    r"|Air|Earth|Fire|Water|Void)"
)
# An ability heads a segment: the start of the text, the far side of a line break, or the sentence
# after the previous ability, and its designator phrase runs to the first colon.
_ABILITY_HEAD = re.compile(
    rf"(?:^|>|(?<=\.)\s|(?<=\.))\s*(?:{_QUALIFIERS}\s+)*"
    rf"(?:{'|'.join(_DESIGNATORS)})\b[^.:<]{{0,20}}:"
)
_MARKUP = re.compile(r"<[^>]+>")


def printed_ability_count(text: str) -> int:
    """How many activated abilities ``text`` spells out.

    Counts the designator phrases that head a segment, so "Battle: ... . Reaction: ..." is two and a
    colon inside an ability's own prose is none. A designator printed as an icon rather than spelled
    out is not counted, so the result is a floor.
    """
    return len(_ABILITY_HEAD.findall(_MARKUP.sub("", text)))


def printed_ability_counts(cards_dir: Path = DEFAULT_CARDS_PATH) -> dict[str, int]:
    """Every card id with the number of activated abilities its printed text spells out.

    A card printed in several sets is counted at its most explicit printing, since a designator
    spelled out on one printing and drawn as an icon on another is the same ability either way.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.

    Returns
    -------
    dict mapping str to int
        Card id to the number of abilities its text spells out.
    """
    counts: dict[str, int] = {}
    for entry in iter_set_entries(cards_dir):
        count = printed_ability_count(entry.text)
        if count > counts.get(entry.card_id, 0):
            counts[entry.card_id] = count
    return counts


def short_ability_registrations(cards_dir: Path = DEFAULT_CARDS_PATH) -> list[str]:
    """
    One human-readable line per card registering fewer activated abilities than its text prints.

    A card implemented in half behaves correctly in the half it has, so nothing else reports it.
    Shortfalls only: :func:`~.printed_ability_count` reads a floor, so a card registering more
    than it appears to print is not reported as a defect.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.

    Returns
    -------
    list of str
        Sorted problem descriptions, empty when every card registers what it prints.
    """
    printed = printed_ability_counts(cards_dir)
    problems = []
    for card_id, registered in sorted(registry._ABILITIES.items()):
        shows = printed.get(card_id, 0)
        if shows > len(registered):
            problems.append(
                f"abilities: {card_id} registers {len(registered)} of the {shows} "
                f"activated abilities its text prints"
            )
    return problems


# The per-card registries registration_audit validates by name. Everything built through the
# registrar is absent on purpose -- those report themselves, which is the point of it.
VALIDATED_REGISTRIES = {
    "_ABILITIES",
    "_INVEST",
    "CHI_DEATH_EXEMPT",
    "_TRIGGERS",
}


# Module-level collections under engine/rules that key on something other than a card. Each is
# named so that a genuinely new registry cannot arrive unnoticed: the guard below insists every
# collection it finds is either validated or listed here, so classifying a new one is a decision
# someone has to make rather than one they can skip.
NOT_KEYED_BY_CARD = {
    "CHOICE_RESOLVERS",  # keyed by the kind of a pending choice
    "_OPTIONAL_COST_ANSWERS",  # likewise -- a bot hint's answers, by resolver
    "CHOICE_PROMPTS",  # likewise, and it lives in decisions
    "POLICIES",  # keyed by policy name
    "AGENTS",  # keyed by agent name
    "FAVOR_ABILITY_COSTS",  # keyed by the arc's FavorAbility
    "FAVOR_ABILITY_EFFECTS",
    "ACTION_TIMINGS",  # keyed by action type
    "PHASE_TIMINGS",  # keyed by phase
    "BATTLE_SEGMENT_TIMINGS",  # keyed by battle segment
    "FIRED_MOMENTS",  # the moments the flow resolves
    "_AFTER_BATTLE_SEGMENT",  # the segment order
    "_ACTION_WORDING",  # keyed by action type, for describe_action
}


COLLECTIONS = ("dict", "set", "frozenset")
# Every package this audit validates a registry in. ``bots`` is here because the ability hints are
# keyed by printed id like any other per-card registry, so the scan has to follow it out of
# ``rules``.
SCANNED = (rules, bots)


# What a registry built through the registrar looks like in source. These need no entry in
# VALIDATED_REGISTRIES: they report themselves at import, so validation reads them whatever they
# are named and wherever they live.
REGISTRAR = ("FlagRegistry", "HandlerRegistry")


def module_level_collections() -> set[str]:
    """Every module-level dict, set and frozenset *defined* in the scanned packages.

    Read from the source rather than from the imported modules, and read recursively. A re-exported
    name shows up in ``vars`` without the module owning it, which is the failure this exists to
    prevent, so a registry in a module nobody thought to list shows up here regardless, including
    one inside a package or in a package the rules layer does not own.
    """
    return {
        name
        for package in SCANNED
        for path in Path(str(package.__file__)).parent.rglob("*.py")
        for name in _collections_defined_in(path)
    }


def _built_by_the_registrar(value: ast.expr | None) -> bool:
    """Whether this binding is a registry the registrar catalogues, which validation finds
    itself."""
    return isinstance(value, ast.Call) and getattr(value.func, "id", "") in REGISTRAR


def _collections_defined_in(path: Path) -> set[str]:
    """The module-level collection names one source file binds, by annotation or by literal."""
    found: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _built_by_the_registrar(node.value):
                continue
            if any(kind in ast.unparse(node.annotation) for kind in COLLECTIONS):
                found.add(node.target.id)
        elif isinstance(node, ast.Assign):
            literal = isinstance(node.value, ast.Dict | ast.Set)
            call = (
                isinstance(node.value, ast.Call)
                and getattr(node.value.func, "id", "") in COLLECTIONS
            )
            if _built_by_the_registrar(node.value):
                continue
            if literal or call:
                found.update(target.id for target in node.targets if isinstance(target, ast.Name))
    return found


def unvalidated_registries(collections: set[str] | None = None) -> list[str]:
    """
    One human-readable line per module-level collection that no check here reads.

    A registry built through :mod:`~yasuki_core.engine.registrar` catalogues itself and needs no
    entry here. One written as a plain dict, set, or frozenset does not, and nothing else notices,
    since :func:`~.unregistered_card_ids` only iterates the registries it is handed. Classifying it
    is a decision someone must make explicitly.

    Parameters
    ----------
    collections : set of str, optional
        The module-level collection names to classify. Default is every one the scan finds.
    """
    found = module_level_collections() if collections is None else collections
    unclassified = found - VALIDATED_REGISTRIES - NOT_KEYED_BY_CARD
    return [
        f"{name} is a module-level registry no check reads; "
        "add it to VALIDATED_REGISTRIES or to NOT_KEYED_BY_CARD"
        for name in sorted(unclassified)
    ]


def main(
    registries: dict[str, frozenset[str]] | None = None,
    trigger_registry: dict[type, dict[str, list[triggers.Trigger]]] | None = None,
) -> int:
    problems = (
        unregistered_card_ids(registries)
        + duplicate_registrations(trigger_registry)
        + unvalidated_registries()
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
