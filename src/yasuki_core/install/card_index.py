import argparse
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

from yasuki_core import DATABASE_DIR
from yasuki_core import card_identity
from yasuki_core.yaml_io import read_yaml

DEFAULT_CARDS_PATH = DATABASE_DIR / "sets"
# Set files a developer keeps on their own machine and does not commit: a fixture Stronghold, a
# set being transcribed. They are absent from a fresh clone, so nothing committed may depend on
# them: the card index skips them, and they register their own set metadata as they load.
LOCAL_SET_SUFFIX = ".local.yaml"
DEFAULT_INDEX_PATH = DATABASE_DIR / "card_ids.txt"
DEFAULT_SET_INFO_PATH = DATABASE_DIR / "set_info.yaml"
TOKENS_SET = "Tokens"


class SetEntry(NamedTuple):
    source: Path
    set_name: str
    card_id: str
    title: str
    keywords: tuple[str, ...]
    creates: tuple[str, ...]
    text: str
    extended_title: str
    pinned: bool


def iter_set_entries(cards_dir: Path) -> Iterator[SetEntry]:
    """
    Every card entry in every set file, in filename order.

    Ids come from :func:`~yasuki_core.card_identity.card_id`, the one derivation the loader
    uses too.

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
    yaml_files = sorted(
        path for path in cards_dir.glob("*.yaml") if not path.name.endswith(LOCAL_SET_SUFFIX)
    )
    if not yaml_files:
        raise ValueError(f"No set files in {cards_dir}")

    for yaml_file in yaml_files:
        data = read_yaml(yaml_file)
        if not isinstance(data, dict):
            raise ValueError(f"{yaml_file} is not a set file")
        for entry in data.get("cards", []):
            title = entry["title"]
            card_id = card_identity.card_id(entry)
            keywords = tuple(entry.get("keywords") or ())
            creates = tuple(entry.get("creates") or ())
            text = entry.get("text") or ""
            extended_title = card_identity.extended_title(entry)
            pinned = bool(entry.get("id"))
            yield SetEntry(
                yaml_file,
                data["set"],
                card_id,
                title,
                keywords,
                creates,
                text,
                extended_title,
                pinned,
            )


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
    # Reprints repeat an id legitimately; two *different* cards sharing one never do. Token ids are
    # stat-descriptive (`courtier_0_3_2`), so that is where a genuine clash is likeliest. Both this
    # index and load_cards keep whichever came first, silently. A reprint may retitle its card, and
    # then it pins the id its earlier printings derive, so pinned and derived titles are compared
    # only among themselves.
    derived: dict[str, SetEntry] = {}
    pinned: dict[str, SetEntry] = {}
    for entry in iter_set_entries(cards_dir):
        claims = pinned if entry.pinned else derived
        first = claims.setdefault(entry.card_id, entry)
        if card_identity.card_slug(first.title) != card_identity.card_slug(entry.title):
            raise ValueError(
                f"{entry.source}: {first.title!r} and {entry.title!r} "
                f"both claim id {entry.card_id!r}"
            )
    ids = derived.keys() | pinned.keys()
    if not ids:
        raise ValueError(f"No card ids found in {cards_dir}")
    return sorted(ids)


def untagged_title_ties(
    cards_dir: Path = DEFAULT_CARDS_PATH,
    set_info_path: Path = DEFAULT_SET_INFO_PATH,
    retired: Mapping[str, str | None] | None = None,
) -> list[str]:
    """
    One line per problem with cards that share an extended title.

    A decklist naming a shared title cannot tell its cards apart by name, so each carries an
    explicit id ending in the ``short_id`` of the set that first printed it, as in ``aulus_goc`` and
    ``aulus_cr3``. The bare title's slug is retired to the card a line without a set names, and no
    two of the cards share a set, so the set a line names picks one. Each card's extended title is
    its newest printing's, as the loader reads it. Tokens are exempt: no decklist names one, and
    their ids already describe their stats.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    set_info_path : path, optional
        The arc-grouped set metadata carrying each set's release date and ``short_id``. Default is
        the packaged ``set_info.yaml``.
    retired : mapping of str to str or None, optional
        Retired id to successor. Default is the committed list,
        :func:`~yasuki_core.card_identity.retired_ids`.

    Returns
    -------
    list of str
        Sorted problem descriptions, empty when every shared title is told apart.

    Raises
    ------
    ValueError
        If a card sharing a title, or reprinted, is in a set ``set_info_path`` gives no
        ``short_id``.
    """
    retired = card_identity.retired_ids() if retired is None else retired
    sets = {
        entry["set_name"]: entry
        for arc in read_yaml(set_info_path)["arcs"]
        for entry in arc["sets"]
    }
    printings: dict[str, list[SetEntry]] = {}
    for entry in iter_set_entries(cards_dir):
        if entry.card_id.endswith("__back"):
            continue
        printings.setdefault(entry.card_id, []).append(entry)

    def set_of(entry: SetEntry) -> dict:
        if "short_id" not in sets.get(entry.set_name, {}):
            raise ValueError(
                f"{entry.source}: {set_info_path.name} gives the set {entry.set_name!r} no short_id"
            )
        return sets[entry.set_name]

    def released(entry: SetEntry, undated: str) -> str:
        return str(set_of(entry).get("release_date") or undated)

    sharing: dict[str, list[str]] = {}
    for card_id, entries in printings.items():
        if {entry.set_name for entry in entries} == {TOKENS_SET}:
            continue
        # The loader counts an undated set as the oldest when it picks the newest printing.
        newest = (
            entries[0] if len(entries) == 1 else max(entries, key=lambda e: released(e, "0000"))
        )
        sharing.setdefault(card_identity.card_slug(newest.extended_title), []).append(card_id)

    problems = []
    for slug, card_ids_sharing in sharing.items():
        if len(card_ids_sharing) < 2:
            continue
        if slug not in retired:
            problems.append(
                f"{slug!r} is shared by {sorted(card_ids_sharing)}; retire it to the card a "
                f"decklist line naming no set means"
            )
        set_holder: dict[str, str] = {}
        for card_id in card_ids_sharing:
            first = min(printings[card_id], key=lambda entry: released(entry, "9999"))
            expected = f"{slug}_{set_of(first)['short_id']}"
            if card_id != expected:
                problems.append(
                    f"{card_id} shares its title with {sorted(set(card_ids_sharing) - {card_id})}; "
                    f"give every printing the id {expected!r}"
                )
            for set_name in {entry.set_name for entry in printings[card_id]}:
                holder = set_holder.setdefault(set_name, card_id)
                if holder != card_id:
                    problems.append(
                        f"{holder} and {card_id} share the title {slug!r} and the set "
                        f"{set_name!r}, so a decklist line cannot tell them apart"
                    )
    return sorted(problems)


def write_index(
    cards_dir: Path = DEFAULT_CARDS_PATH,
    index_path: Path = DEFAULT_INDEX_PATH,
    retired: Mapping[str, str | None] | None = None,
) -> int:
    """
    Regenerate the committed card-id index from the YAML and return how many ids it holds.

    Saved decks and exported decklists hold card ids, so an id may leave the index only once it is
    listed as retired, with the id that replaces it.

    Parameters
    ----------
    cards_dir : path, optional
        Directory of per-set YAML files. Default is the packaged ``sets`` directory.
    index_path : path, optional
        File to write, one id per line. Default is the packaged ``card_ids.txt``.
    retired : mapping of str to str or None, optional
        Retired id to successor. Default is the committed list,
        :func:`~yasuki_core.card_identity.retired_ids`.

    Raises
    ------
    ValueError
        If the YAML no longer derives an id the existing index holds and that id is not retired, or
        if two cards share an extended title without the ids that set them apart.
    """
    ids = card_ids(cards_dir)
    if ties := untagged_title_ties(cards_dir):
        raise ValueError("\n".join(ties))
    if index_path.exists():
        retired = card_identity.retired_ids() if retired is None else retired
        dropped = read_index(index_path) - set(ids) - retired.keys()
        if dropped:
            raise ValueError(
                f"The card YAML no longer derives {sorted(dropped)}. List each in "
                f"{card_identity.RETIRED_IDS_PATH.name} with the id that replaces it, or null."
            )
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
