import difflib
import re
import sys
from pathlib import Path

from yasuki_core.engine.rules import (
    abilities,
    attachments,
    economy,
    equip,
    policies,
    state_rules,
    triggers,
)

# Without this the registries are empty and every check below passes vacuously.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries, read_index


def registered_card_ids() -> dict[str, frozenset[str]]:
    """
    Every card id the engine keys a per-card handler on, grouped by the registry holding it.

    ``CHOICE_RESOLVERS`` is absent by design. It keys on the *kind* of a pending choice rather than on
    a card — ``modest_farm_straighten`` and ``sincerity_seed`` name steps in a sequence, not cards —
    so validating it against the card index would report failures that are not defects.
    """
    return {
        "abilities": frozenset(abilities._ABILITIES),
        "invest abilities": frozenset(abilities._INVEST),
        "enters unbowed": frozenset(abilities._ENTERS_UNBOWED),
        "may remain bowed": frozenset(abilities.MAY_REMAIN_BOWED),
        "bow waivers": frozenset(abilities.BOW_WAIVERS),
        "gold handlers": frozenset(economy.GOLD_HANDLERS),
        "gold self grants": frozenset(economy.GOLD_SELF_GRANT),
        "recruit discounts": frozenset(economy.RECRUIT_DISCOUNTS),
        "invest discounts": frozenset(economy.INVEST_DISCOUNTS),
        "keyword grants": frozenset(economy.KEYWORD_GRANTS),
        "province strength grants": frozenset(economy.PROVINCE_STRENGTH_GRANTS),
        "ability heuristics": frozenset(policies.ABILITY_HEURISTICS),
        "attachment grants": frozenset(attachments.ATTACHMENT_GRANTS),
        "attach restrictions": frozenset(equip.ATTACH_RESTRICTIONS),
        "triggers": frozenset(
            card_id for by_card in triggers._TRIGGERS.values() for card_id in by_card
        ),
    }


def card_keyed_data() -> dict[str, frozenset[str]]:
    """Every card id the engine names as *data* rather than as a handler, grouped by the list
    holding it.

    Kept apart from :func:`registered_card_ids` because these ids do not live in a set module — a
    card excepted from a rulebook rule is a property of the card, listed beside the rule it excepts,
    and the layout scan would report every one of them as a registration it could not find. They are
    validated against the card index all the same.
    """
    return {"chi death exemptions": state_rules.CHI_DEATH_EXEMPT}


def duplicate_registrations(
    trigger_registry: dict[type, dict[str, list[triggers.Trigger]]] | None = None,
) -> list[str]:
    """
    One human-readable line per card id whose trigger is registered more than once.

    Only ``_TRIGGERS`` can hold a duplicate. It appends, so a handler copy-pasted into a second module
    makes the trigger fire twice — a wrong game state rather than a shadowed one. The dict registries
    overwrite instead, and the three written as literals are covered by ruff's F601.

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
    for registry, card_ids in sorted(registries.items()):
        for card_id in sorted(card_ids - known):
            closest = difflib.get_close_matches(card_id, known, n=1)
            hint = f" — did you mean {closest[0]}?" if closest else ""
            problems.append(f"{registry}: no card has the id {card_id!r}{hint}")
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
# An ability heads a segment — the start of the text, the far side of a line break, or the sentence
# after the previous ability — and its designator phrase runs to the first colon.
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
    Shortfalls alone: :func:`printed_ability_count` reads a floor, so a card registering more than
    it appears to print is a limit of the count rather than a defect.

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
    for card_id, registered in sorted(abilities._ABILITIES.items()):
        shows = printed.get(card_id, 0)
        if shows > len(registered):
            problems.append(
                f"abilities: {card_id} registers {len(registered)} of the {shows} "
                f"activated abilities its text prints"
            )
    return problems


def main(
    registries: dict[str, frozenset[str]] | None = None,
    trigger_registry: dict[type, dict[str, list[triggers.Trigger]]] | None = None,
) -> int:
    problems = unregistered_card_ids(registries) + duplicate_registrations(trigger_registry)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
