import difflib
import sys

from yasuki_core.engine.rules import abilities, attachments, economy, equip, triggers

# Without this the registries are empty and every check below passes vacuously.
from yasuki_core.engine.rules import cards  # noqa: F401
from yasuki_core.install.card_index import read_index


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
        "production boosts": frozenset(abilities._PRODUCTION_BOOST),
        "gold handlers": frozenset(economy.GOLD_HANDLERS),
        "recruit discounts": frozenset(economy.RECRUIT_DISCOUNTS),
        "keyword grants": frozenset(economy.KEYWORD_GRANTS),
        "province strength grants": frozenset(economy.PROVINCE_STRENGTH_GRANTS),
        "attachment grants": frozenset(attachments.ATTACHMENT_GRANTS),
        "attach restrictions": frozenset(equip.ATTACH_RESTRICTIONS),
        "triggers": frozenset(
            card_id for by_card in triggers._TRIGGERS.values() for card_id in by_card
        ),
    }


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
        registries = registered_card_ids()

    known = read_index()
    problems: list[str] = []
    for registry, card_ids in sorted(registries.items()):
        for card_id in sorted(card_ids - known):
            closest = difflib.get_close_matches(card_id, known, n=1)
            hint = f" — did you mean {closest[0]}?" if closest else ""
            problems.append(f"{registry}: no card has the id {card_id!r}{hint}")
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
