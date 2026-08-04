import argparse
from pathlib import Path

from yasuki_core.install.card_index import DEFAULT_CARDS_PATH, iter_set_entries


def cards_by_set(cards_dir: Path = DEFAULT_CARDS_PATH) -> dict[str, set[str]]:
    """
    Every card id in each set, keyed by set name.

    A reprint counts toward every set it appears in, not only its first, so a set is credited for the
    cards a player can actually field from it.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    """
    by_set: dict[str, set[str]] = {}
    for entry in iter_set_entries(cards_dir):
        by_set.setdefault(entry.set_name, set()).add(entry.card_id)
    return by_set


def coverage(implemented: set[str], by_set: dict[str, set[str]]) -> list[tuple[str, int, int]]:
    """
    ``(set name, implemented, total)`` per set, richest coverage first, then alphabetically.

    Parameters
    ----------
    implemented : set of str
        Card ids the engine has a handler for.
    by_set : dict mapping str to set of str
        Set name to the card ids it contains.
    """
    rows = [(name, len(ids & implemented), len(ids)) for name, ids in by_set.items()]
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Per-set card implementation coverage")
    parser.add_argument(
        "--cards", type=Path, default=DEFAULT_CARDS_PATH, help="per-set YAML directory"
    )
    parser.add_argument("--all", action="store_true", help="include sets with nothing implemented")
    args = parser.parse_args()

    # Imported here to keep the engine off the data pipeline's import path.
    from yasuki_core.engine.rules.card_registry import registered_card_ids

    implemented = set().union(*registered_card_ids().values())
    rows = coverage(implemented, cards_by_set(args.cards))
    shown = rows if args.all else [row for row in rows if row[1]]

    for name, done, total in shown:
        print(f"{done:4}/{total:<5} {done / total:6.1%}  {name}")

    covered_sets = sum(1 for row in rows if row[1])
    print(f"\n{covered_sets} of {len(rows)} sets have at least one implemented card")


if __name__ == "__main__":
    main()
