import argparse
from pathlib import Path

import yaml

from yasuki_core import DATABASE_DIR
from yasuki_core.install.yaml_to_sql import card_slug

DEFAULT_CARDS_PATH = DATABASE_DIR / "sets"
DEFAULT_INDEX_PATH = DATABASE_DIR / "card_ids.txt"


def card_ids(cards_dir: Path) -> list[str]:
    """
    Every distinct card id in the per-set YAML, sorted.

    Ids are derived exactly as :func:`yasuki_core.install.yaml_to_sql.load_cards` derives them: an
    explicit ``id``, or a slug of the extended title, with ``__back`` appended for the reverse face of
    a double-faced card.

    Parameters
    ----------
    cards_dir : path
        Directory of per-set YAML files.

    Returns
    -------
    list of str
        Sorted card ids, deduplicated across the sets a card is printed in.

    Raises
    ------
    ValueError
        If a file in ``cards_dir`` is not a set file, or if the directory yields no ids at all.
    """
    ids: set[str] = set()
    for yaml_file in sorted(cards_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{yaml_file} is not a set file")
        for entry in data.get("cards", []):
            card_id = entry.get("id") or card_slug(entry.get("extended_title") or entry["title"])
            ids.add((card_id + "__back") if entry.get("is_back") else card_id)
    if not ids:
        raise ValueError(f"No card ids found in {cards_dir}")
    return sorted(ids)


def write_index(cards_dir: Path = DEFAULT_CARDS_PATH, index_path: Path = DEFAULT_INDEX_PATH) -> int:
    """
    Regenerate the committed card-id index from the YAML and return how many ids it holds.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    index_path : path, optional
        File to write, one id per line. Default is the packaged ``card_ids.txt``.
    """
    ids = card_ids(cards_dir)
    index_path.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return len(ids)


def read_index(index_path: Path = DEFAULT_INDEX_PATH) -> frozenset[str]:
    """
    Read the committed card-id index, the fast stand-in for parsing the YAML.

    Parameters
    ----------
    index_path : path, optional
        File to read, one id per line. Default is the packaged ``card_ids.txt``.
    """
    return frozenset(index_path.read_text(encoding="utf-8").splitlines())


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate the committed card-id index")
    parser.add_argument(
        "--cards", type=Path, default=DEFAULT_CARDS_PATH, help="per-set YAML directory"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_INDEX_PATH, help="index file to write")
    args = parser.parse_args()
    print(f"{write_index(args.cards, args.out)} card ids written to {args.out}")


if __name__ == "__main__":
    main()
