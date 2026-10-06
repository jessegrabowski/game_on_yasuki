import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from yasuki_core.paths import DATABASE_DIR
from yasuki_core.yaml_io import read_yaml

# The experience qualifier an Experienced or Inexperienced keyword prints: a level, a set code, or
# both, and never the alternate title some of them carry ("Experienced 2 Shinjo Yokatsu").
_EXPERIENCE = re.compile(r"(?:In)?[Ee]xperienced(?: ?\d+(?:\.\d+)?)?(?:KYD|CW|CoM)?")
EXPERIENCE_SEPARATOR = " • "
SUBTITLE_SEPARATOR = ", "
RETIRED_IDS_PATH = DATABASE_DIR / "retired_ids.yaml"


def card_slug(text: str) -> str:
    """Slug used as the card id when the YAML entry carries no explicit `id`."""
    s = text.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _experience_keyword(keywords: Iterable[str]) -> re.Match[str] | None:
    """The first Experienced or Inexperienced keyword among ``keywords``, matched."""
    return next(filter(None, map(_EXPERIENCE.match, keywords)), None)


def experience_label(keywords: Iterable[str]) -> str | None:
    """The experience qualifier among ``keywords``, such as "Experienced 2KYD", or None for a card
    printing no Experienced or Inexperienced keyword."""
    match = _experience_keyword(keywords)
    return match.group() if match else None


def experience_alias(keywords: Iterable[str]) -> str | None:
    """The other card's title an Experienced or Inexperienced keyword names, as "Bayushi Tenzan" in
    "Experienced Bayushi Tenzan", or None where the keyword names none."""
    match = _experience_keyword(keywords)
    return match.string[match.end() :].strip() or None if match else None


def subtitled_title(entry: Mapping) -> str:
    """The title a printing shows, then ", " and its subtitle where it has one."""
    if subtitle := entry.get("subtitle"):
        return f"{entry['title']}{SUBTITLE_SEPARATOR}{subtitle}"
    return entry["title"]


def extended_title(entry: Mapping) -> str:
    """The title a printing shows, qualified by its subtitle and its experience.

    Parameters
    ----------
    entry : mapping
        A card entry from a set's YAML ``cards`` list.

    Returns
    -------
    str
        The title, then ", " and the subtitle, then " • " and the experience qualifier, each only
        where the printing has one.
    """
    title = subtitled_title(entry)
    if label := experience_label(entry.get("keywords") or ()):
        title = f"{title}{EXPERIENCE_SEPARATOR}{label}"
    return title


def card_id(entry: Mapping) -> str:
    """The id of the card ``entry`` prints: its explicit ``id``, or the slug of its extended title,
    with ``__back`` appended for the reverse face of a double-faced card."""
    base = entry.get("id") or card_slug(extended_title(entry))
    return f"{base}__back" if entry.get("is_back") else base


@cache
def retired_ids(path: Path = RETIRED_IDS_PATH) -> dict[str, str | None]:
    """Each retired card id mapped to the id that replaced it, or to None for a card that is
    gone."""
    return read_yaml(path) or {}


def current_id(card_id: str, retired: Mapping[str, str | None] | None = None) -> str | None:
    """The id ``card_id`` names today: itself unless retired, else its successor's current id, or
    None when the chain ends at a card that is gone.

    Parameters
    ----------
    card_id : str
        An id as a deck or decklist stored it.
    retired : mapping of str to str or None, optional
        Retired id to successor. Default is the committed list, :func:`retired_ids`.

    Raises
    ------
    ValueError
        If the retired ids form a cycle.
    """
    retired = retired_ids() if retired is None else retired
    current, seen = card_id, set()
    while current in retired:
        if current in seen:
            raise ValueError(f"retired card ids form a cycle through {current!r}")
        seen.add(current)
        successor = retired[current]
        if successor is None:
            return None
        current = successor
    return current


def printed_sets(record: Mapping) -> list[str]:
    """The sets a card record's ``prints`` list says it was printed in."""
    return [printing["set_name"] for printing in record.get("prints") or ()]


@dataclass(frozen=True, slots=True)
class NameIndex[R: Mapping]:
    """Card records keyed by the slugs a decklist name resolves through.

    Attributes
    ----------
    by_slug : mapping of str to mapping
        Each card's id, then the slug of its current extended title, to the card.
    sharing : mapping of str to tuple of mapping
        The slug of an extended title two or more cards share, to those cards.
    sets_of : callable
        The names of the sets a card was printed in.
    retired : mapping of str to str or None
        Retired id to successor, the list both the keys and the lookup follow.
    """

    by_slug: Mapping[str, R]
    sharing: Mapping[str, tuple[R, ...]]
    sets_of: Callable[[R], Iterable[str]]
    retired: Mapping[str, str | None]


def name_index[R: Mapping](
    records: Iterable[R],
    retired: Mapping[str, str | None] | None = None,
    sets_of: Callable[[R], Iterable[str]] = printed_sets,
) -> NameIndex[R]:
    """Index card records by the slugs a decklist name resolves through.

    A deck file names a card by the extended title it showed when the deck was written, and that
    slugs to the card's id unless a later reprint added a subtitle to the title the card shows. Ids
    are keyed first, then the slug of each card's current extended title, so an id always wins. A
    slug that is a retired id is left to :func:`resolve_name`, which follows it to its successor.

    Parameters
    ----------
    records : iterable of mapping
        Card records, each carrying ``card_id``, ``name`` and optionally ``extended_title``.
    retired : mapping of str to str or None, optional
        Retired id to successor. Default is the committed list, :func:`retired_ids`.
    sets_of : callable, optional
        The names of the sets a record was printed in, which tell apart cards sharing a title.
        Default reads the record's ``prints`` list.

    Returns
    -------
    NameIndex
        The index :func:`resolve_name` reads.
    """
    records = list(records)
    retired = retired_ids() if retired is None else retired
    by_slug = {record["card_id"]: record for record in records}
    titled: dict[str, list[R]] = {}
    for record in records:
        slug = card_slug(record.get("extended_title") or record["name"])
        titled.setdefault(slug, []).append(record)
        if slug not in retired:
            by_slug.setdefault(slug, record)
    sharing = {slug: tuple(cards) for slug, cards in titled.items() if len(cards) > 1}
    return NameIndex(by_slug, sharing, sets_of, retired)


def resolve_name[R: Mapping](
    index: NameIndex[R], name: str, set_name: str | None = None
) -> R | None:
    """The record a decklist line names.

    Cards that share an extended title are told apart by the set the line names. Otherwise the
    name's slug is looked up, a retired id followed to its successor.

    Parameters
    ----------
    index : NameIndex
        As built by :func:`name_index`.
    name : str
        The card name the line gives.
    set_name : str, optional
        The set the line gives, if any.

    Returns
    -------
    mapping or None
        The card, or None for a name no card answers to.
    """
    slug = card_slug(name)
    if set_name is not None:
        for record in index.sharing.get(slug, ()):
            if set_name in index.sets_of(record):
                return record
    if slug in index.by_slug:
        return index.by_slug[slug]
    successor = current_id(slug, index.retired)
    return index.by_slug.get(successor) if successor is not None else None
