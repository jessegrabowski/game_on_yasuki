import argparse
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from yasuki_core import DATABASE_DIR

DEFAULT_CARDS_PATH = DATABASE_DIR / "sets"
# Set files a developer keeps on their own machine and does not commit — a fixture Stronghold, a
# set being transcribed. They are absent from a fresh clone, so nothing committed may depend on
# them: the card index skips them, and they register their own set metadata as they load.
LOCAL_SET_SUFFIX = ".local.yaml"
DEFAULT_INDEX_PATH = DATABASE_DIR / "card_ids.txt"


class SetEntry(NamedTuple):
    source: Path
    set_name: str
    card_id: str
    title: str
    keywords: tuple[str, ...]
    creates: tuple[str, ...]


def iter_set_entries(cards_dir: Path) -> Iterator[SetEntry]:
    """
    Every card entry in every set file, in filename order.

    Ids are derived exactly as :func:`yasuki_core.install.yaml_to_sql.load_cards` derives them: an
    explicit ``id``, or a slug of the extended title, with ``__back`` appended for the reverse face of
    a double-faced card. Every consumer reads the data through here, so the derivation has one
    definition and cannot drift between them.

    Local set files are skipped. The committed index has to match a fresh clone, which holds none of
    them, so a card only one machine has must not reach it.

    Parameters
    ----------
    cards_dir : path
        Directory of per-set YAML files.

    Raises
    ------
    ValueError
        If ``cards_dir`` holds no set files, or if one of them is not a set file.
    """
    # Imported here rather than at module scope: yaml_to_sql pulls in the Postgres driver, and
    # read_index is on the pre-commit path, where the cost buys nothing.
    import yaml

    from yasuki_core.install.yaml_to_sql import card_slug

    yaml_files = sorted(
        path for path in cards_dir.glob("*.yaml") if not path.name.endswith(LOCAL_SET_SUFFIX)
    )
    if not yaml_files:
        raise ValueError(f"No set files in {cards_dir}")

    for yaml_file in yaml_files:
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{yaml_file} is not a set file")
        for entry in data.get("cards", []):
            title = entry["title"]
            card_id = entry.get("id") or card_slug(entry.get("extended_title") or title)
            if entry.get("is_back"):
                card_id += "__back"
            keywords = tuple(entry.get("keywords") or ())
            creates = tuple(entry.get("creates") or ())
            yield SetEntry(yaml_file, data["set"], card_id, title, keywords, creates)


def card_ids(cards_dir: Path) -> list[str]:
    """
    Every distinct card id in the per-set YAML, sorted.

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
        If two different cards claim one id, or if the set files hold no cards at all.
    """
    titles_by_id: dict[str, str] = {}
    for entry in iter_set_entries(cards_dir):
        # Reprints repeat an id legitimately; two *different* cards sharing one never do. Token ids
        # are stat-descriptive (`courtier_0_3_2`), so that is where a genuine clash is likeliest —
        # and both this index and load_cards keep whichever came first, silently.
        claimed = titles_by_id.setdefault(entry.card_id, entry.title)
        if claimed != entry.title:
            raise ValueError(
                f"{entry.source}: {claimed!r} and {entry.title!r} both claim id {entry.card_id!r}"
            )
    if not titles_by_id:
        raise ValueError(f"No card ids found in {cards_dir}")
    return sorted(titles_by_id)


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
