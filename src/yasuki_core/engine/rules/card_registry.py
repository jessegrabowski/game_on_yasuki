import difflib
import sys

from yasuki_core.engine.rules import abilities, economy, triggers
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
        "triggers": frozenset(
            card_id for by_card in triggers._TRIGGERS.values() for card_id in by_card
        ),
    }


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


def main(registries: dict[str, frozenset[str]] | None = None) -> int:
    problems = unregistered_card_ids(registries)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
