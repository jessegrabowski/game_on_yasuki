import ast
import datetime
import difflib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
import re
import sys
from pathlib import Path

from yasuki_core.engine.rules.abilities import registry
from yasuki_core import DATABASE_DIR, ruleset
from yasuki_core.engine.rules.abilities.model import Ability, CardLocation, Interrupt
from yasuki_core.engine.rules.effects import Effect
from yasuki_core.yaml_io import read_yaml
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
from yasuki_core.engine.rules.rulebook import proxies
from yasuki_core.engine import rules
from yasuki_core.install.card_index import (
    DEFAULT_CARDS_PATH,
    SetEntry,
    iter_set_entries,
    read_index,
)
from yasuki_core.game_pieces.text_split import split_text_box

DEFAULT_SET_INFO_PATH = DATABASE_DIR / "set_info.yaml"


def registered_card_ids() -> dict[str, frozenset[str]]:
    """
    Every card id the engine keys a per-card handler on, grouped by the registry holding it.

    Every registry built through :mod:`~yasuki_core.engine.registrar` reports itself, so a new one
    is validated without being listed here. The ones below are not built that way: they keep
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
        "interrupts": frozenset(registry._INTERRUPTS),
        "condition watches": frozenset(triggers._WATCHES),
        "triggers": frozenset(
            card_id
            for by_zone in triggers._TRIGGERS.values()
            for by_card in by_zone.values()
            for card_id in by_card
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
    trigger_registry: dict[type, dict[CardLocation, dict[str, list[triggers.Registration]]]]
    | None = None,
) -> list[str]:
    """
    One human-readable line per card id whose trigger is registered more than once.

    Only ``_TRIGGERS`` can hold a duplicate. It appends, so a handler copy-pasted into a second
    module fires the trigger twice, producing a wrong game state rather than a loud failure. Every
    other per-card registry raises on a repeated registration.

    Parameters
    ----------
    trigger_registry : dict, optional
        Event type to a dict of :class:`~yasuki_core.engine.rules.vocabulary.locations.CardLocation`
        to a dict of card id to its :class:`~yasuki_core.engine.rules.triggers.Registration`
        records. Defaults to the engine's own trigger registry.
    """
    if trigger_registry is None:
        trigger_registry = triggers._TRIGGERS

    problems = []
    for event_type, by_zone in sorted(trigger_registry.items(), key=lambda item: item[0].__name__):
        for location, by_card in sorted(by_zone.items(), key=lambda item: item[0].value):
            for card_id, hooks in sorted(by_card.items()):
                for name, count in _read_together_counts(hooks).items():
                    problems.append(
                        f"triggers: {card_id} registers {name} for {event_type.__name__} "
                        f"{count} times in the {location.value}"
                    )
    return problems


def _read_together_counts(hooks: Sequence[triggers.Registration]) -> dict[str, int]:
    """Each trigger name some ruleset would read more than once, with how many times: the same
    function registered twice under one ruleset, or once for every arc and again under one."""
    by_name: dict[str, list[str | None]] = {}
    for held in hooks:
        by_name.setdefault(held.trigger.__qualname__, []).append(held.ruleset)
    counts = {}
    for name, rulesets in sorted(by_name.items()):
        unscoped = rulesets.count(None)
        per_ruleset = Counter(each for each in rulesets if each is not None)
        widest = unscoped + max(per_ruleset.values(), default=0)
        if widest > 1:
            counts[name] = widest
    return counts


# Back faces whose printed text the engine cannot model yet, so their fronts stand implemented
# alone. The Palatial Estate's back gives the seat's Favor actions Repeatable, which no rule reads.
UNMODELED_BACKS = frozenset({"the_palatial_estate_of_the_crane__back"})


def unregistered_back_faces(
    registries: dict[str, frozenset[str]] | None = None, known: frozenset[str] | None = None
) -> list[str]:
    """
    One human-readable line per implemented card whose back face has no registration at all.

    A double-faced card is two card ids, and a front implemented without its back plays as a
    blank once flipped, which nothing else reports. A back listed in ``UNMODELED_BACKS`` is a
    known gap and is not reported.

    Parameters
    ----------
    registries : dict mapping str to frozenset of str, optional
        Registry name to the card ids it keys on. Defaults to the engine's own registries.
    known : frozenset of str, optional
        Every card id. Defaults to the packaged index.
    """
    if registries is None:
        registries = registered_card_ids()
    if known is None:
        known = read_index()

    registered = frozenset().union(*registries.values())
    return [
        f"{card_id} is implemented but its back face {card_id}__back is not"
        for card_id in sorted(registered)
        if f"{card_id}__back" in known
        and f"{card_id}__back" not in registered
        and f"{card_id}__back" not in UNMODELED_BACKS
    ]


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

    known = read_index() | frozenset(proxies.RULEBOOK_PROXY_PRINTS)
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
# A printed designator whose registration goes by another name: the older arcs print Reaction for
# the action the ShE datasheet calls a Response, and the engine registers both as RESPONSE.
_AS_REGISTERED = {"Reaction": "Response"}


def _registered_designators(printed: Sequence[str]) -> frozenset[str]:
    return frozenset(_AS_REGISTERED.get(word, word) for word in printed)


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
REPEATABLE = "Repeatable"


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
    than it appears to print is not reported as a defect. A Recruit timing counts as one ability,
    since it implements a printed "Political Open: Recruit it" of its own.

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
    abilities = registry.ability_registrations()
    registering = set(abilities) | set(registry._INTERRUPTS) | set(registry.RECRUIT_TIMINGS)
    for card_id in sorted(registering):
        shows = printed.get(card_id, 0)
        registered = (
            len(abilities.get(card_id, ()))
            + (card_id in registry._INTERRUPTS)
            + (card_id in registry.RECRUIT_TIMINGS)
        )
        if shows > registered:
            problems.append(
                f"abilities: {card_id} registers {registered} of the {shows} "
                f"activated abilities its text prints"
            )
    return problems


def printed_abilities(
    cards_dir: Path = DEFAULT_CARDS_PATH,
) -> dict[str, set[tuple[frozenset[str], frozenset[str], frozenset[str]]]]:
    """Every card id with the ``(designators, keywords, modifiers)`` triples its printed abilities
    carry.

    Read across every printing, since a keyword one printing spells out another may draw as an
    icon, and the triples are a set so a printing that repeats the wording adds nothing.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.

    Returns
    -------
    dict mapping str to set of tuple
        Card id to its ``(designators, keywords, modifiers)`` triples, each a frozenset of str.
    """
    printed: dict[str, set[tuple[frozenset[str], frozenset[str], frozenset[str]]]] = {}
    for entry in iter_set_entries(cards_dir):
        for ability in split_text_box(entry.text).abilities:
            printed.setdefault(entry.card_id, set()).add(
                (
                    _registered_designators(ability.designators),
                    frozenset(ability.keywords),
                    frozenset(ability.modifiers),
                )
            )
    return printed


def _printed_designators(ability: Ability) -> frozenset[str]:
    return frozenset(timing.name.capitalize() for timing in ability.timings)


def _spelled(keywords: frozenset[str]) -> str:
    return " ".join(sorted(keywords)) or "none"


def mislabeled_abilities(
    cards_dir: Path = DEFAULT_CARDS_PATH,
    abilities: Mapping[str, Sequence[Ability]] | None = None,
) -> list[str]:
    """
    One human-readable line per registered ability whose ``keywords`` or ``repeatable`` disagree
    with the card's text.

    A registration is matched to the printed abilities whose designators cover its timings, so one
    registering the Open half of a printed Battle/Open is still judged, and its keywords must equal
    one of theirs. An ability the text does not print under those designators, such as a granted or
    rulebook one, is left alone: only what is printed can contradict a registration.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    abilities : mapping of str to sequence of :class:`~yasuki_core.engine.rules.abilities.model.Ability`, optional
        Card id to its registered abilities. Defaults to the ones in force under the active ruleset.

    Returns
    -------
    list of str
        Sorted problem descriptions, empty when every registration reads as its card prints.
    """
    if abilities is None:
        abilities = registry.ability_registrations()
    printed = printed_abilities(cards_dir)
    problems = []
    for card_id in sorted(abilities):
        for ability in abilities[card_id]:
            designators = _printed_designators(ability)
            matching = {
                (kws, mods) for desig, kws, mods in printed.get(card_id, ()) if designators <= desig
            }
            if not matching:
                continue
            under = "/".join(sorted(designators))
            if ability.keywords not in {kws for kws, _ in matching}:
                authored = _spelled(ability.keywords)
                printed_words = " or ".join(sorted({_spelled(kws) for kws, _ in matching}))
                problems.append(
                    f"abilities: {card_id} registers keywords {authored} on its {under} ability, "
                    f"whose text prints {printed_words}"
                )
            in_play = CardLocation.HAND not in ability.located_at
            prints_repeatable = any(REPEATABLE in mods for _, mods in matching)
            if in_play and ability.repeatable != prints_repeatable:
                verb = "registers" if ability.repeatable else "does not register"
                problems.append(
                    f"abilities: {card_id} {verb} its {under} ability as Repeatable, "
                    f"and its text {'prints' if prints_repeatable else 'does not print'} it"
                )
    return problems


# Sorts before every real release date, so a set with no recorded date never counts as newest.
_UNDATED = datetime.date(1, 1, 1)


def _arcs_of(ruleset_name: str | None) -> tuple[str, ...]:
    """The arcs the named ruleset governs, or the active ruleset's for a registration naming none.
    Empty when no ruleset carries the name."""
    name = ruleset.ACTIVE.name if ruleset_name is None else ruleset_name
    for held in vars(ruleset).values():
        if isinstance(held, ruleset.Ruleset) and held.name == name:
            return held.arcs
    return ()


def modeled_printings(
    cards_dir: Path = DEFAULT_CARDS_PATH, set_info_path: Path = DEFAULT_SET_INFO_PATH
) -> Callable[[str, str | None], SetEntry | None]:
    """A lookup from a card id and a ruleset name to the printing a registration under that
    ruleset models: the card's newest printing among the ruleset's arcs, or its newest anywhere
    when it has none there, which is the text the database gives the card.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    set_info_path : path, optional
        The arc-grouped set metadata carrying each set's release date. Default is the packaged
        ``set_info.yaml``.

    Returns
    -------
    callable
        Maps ``(card_id, ruleset_name)`` to the modeled :class:`~.SetEntry`, or None for an id no
        set prints with text.
    """
    metadata = read_yaml(set_info_path)
    arc_of, released = {}, {}
    for arc in metadata["arcs"]:
        for entry in arc.get("sets", ()):
            arc_of[entry["set_name"]] = arc["name"]
            released[entry["set_name"]] = entry.get("release_date") or _UNDATED
    printings: dict[str, list[SetEntry]] = {}
    for entry in iter_set_entries(cards_dir):
        if entry.text.strip():
            printings.setdefault(entry.card_id, []).append(entry)

    def lookup(card_id: str, ruleset_name: str | None) -> SetEntry | None:
        held = printings.get(card_id, [])
        arcs = _arcs_of(ruleset_name)
        in_arcs = [entry for entry in held if arc_of.get(entry.set_name) in arcs]
        candidates = in_arcs or held
        if not candidates:
            return None
        return max(candidates, key=lambda entry: released.get(entry.set_name, _UNDATED))

    return lookup


def unprinted_registrations(
    cards_dir: Path = DEFAULT_CARDS_PATH,
    abilities: Mapping[str, Sequence[Ability]] | None = None,
    interrupts: Mapping[str, Sequence[Interrupt[Effect]]] | None = None,
) -> list[str]:
    """
    One human-readable line per registration whose ``printed_index`` names no ability its card
    prints, or one the registration could not be.

    A registration with no ``label`` shows the printed ability its index names, read off the card's
    text, so the index has to land on an ability the modeled printing prints under designators
    that cover the registration's timings. A registration with a ``label`` is one the text prints
    no ability for, and is left alone.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    abilities : mapping of str to sequence of :class:`~yasuki_core.engine.rules.abilities.model.Ability`, optional
        Card id to its registered abilities. Defaults to every registration, whatever its ruleset,
        since each is judged against the printing its own ruleset models.
    interrupts : mapping of str to sequence of :class:`~yasuki_core.engine.rules.abilities.model.Interrupt`, optional
        Card id to its registered Interrupts. Defaults to every registration.

    Returns
    -------
    list of str
        Sorted problem descriptions, empty when every index lands where it should.
    """
    if abilities is None:
        abilities = registry._ABILITIES
    if interrupts is None:
        interrupts = registry._INTERRUPTS
    printing_of = modeled_printings(cards_dir)
    problems: list[str] = []
    for card_id in sorted(set(abilities) | set(interrupts)):
        held: list[tuple[str, int, str | None, frozenset[str]]] = [
            (
                f"{card_id}[{a.key}]" if a.key else card_id,
                a.printed_index,
                a.ruleset,
                frozenset(t.name.capitalize() for t in a.timings),
            )
            for a in abilities.get(card_id, ())
            if a.label is None
        ]
        held += [
            (card_id, i.printed_index, i.ruleset, frozenset({"Interrupt"}))
            for i in interrupts.get(card_id, ())
            if i.label is None
        ]
        for name, index, ruleset_name, timings in held:
            printing = printing_of(card_id, ruleset_name)
            if printing is None:
                # An id no set prints is the unregistered-id check's to report, not a wrong index.
                continue
            printed = split_text_box(printing.text).abilities
            if index >= len(printed):
                problems.append(
                    f"abilities: {name} names printed ability {index}, and its text prints "
                    f"{len(printed)}"
                )
                continue
            ability = printed[index]
            designators = _registered_designators(ability.designators)
            if designators and not timings <= designators:
                problems.append(
                    f"abilities: {name} names printed ability {index}, which is "
                    f"{'/'.join(ability.designators)} where the registration is "
                    f"{'/'.join(sorted(timings))}"
                )
    return sorted(problems)


# The per-card registries registration_audit validates by name. Everything built through the
# registrar is absent on purpose -- those report themselves, which is the point of it.
VALIDATED_REGISTRIES = {
    "_ABILITIES",
    "_INVEST",
    "_INTERRUPTS",
    "CHI_DEATH_EXEMPT",
    "_TRIGGERS",
    "_WATCHES",
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
    "ACTION_TIMINGS",  # keyed by action type
    "PHASE_TIMINGS",  # keyed by phase
    "BATTLE_SEGMENT_TIMINGS",  # keyed by battle segment
    "FIRED_MOMENTS",  # the moments the flow resolves
    "_AFTER_BATTLE_SEGMENT",  # the segment order
    "_ACTION_WORDING",  # keyed by action type, for describe_action
    "_RULEBOOK_TRIGGERS",  # keyed by event type: the rulebook's own triggers, no card behind them
    "WINDOWS",  # the event types a step fires before committing
    "_CONDITIONS",  # keyed by Condition: what a conditional modifier asks of a card
    "KEYWORD_ABILITIES",  # keyed by keyword: the abilities one confers on every card carrying it
    "LOCATION_ABILITIES",  # keyed by location: the abilities it confers on every card sitting there
    "KEYWORD_INTERRUPTS",  # keyed by keyword: the Interrupts one confers on every card carrying it
    "_LOCATION_ZONE_ROLES",  # the zone role each location off the battlefield names
    "RULEBOOK_PROXY_PRINTS",  # keyed by an engine-owned proxy id, which names no catalog card
    "FAVOR_ABILITY_KEYS",  # the keys of the abilities on the Favor proxies
    "_FAVOR_PROXY_CARD_IDS",  # each seat's Favor proxy, by the card id it is dealt under
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
    trigger_registry: dict[type, dict[CardLocation, dict[str, list[triggers.Registration]]]]
    | None = None,
) -> int:
    problems = (
        unregistered_card_ids(registries)
        + unregistered_back_faces(registries)
        + duplicate_registrations(trigger_registry)
        + unvalidated_registries()
        + mislabeled_abilities()
        + unprinted_registrations()
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
