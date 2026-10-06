import re
from collections.abc import Iterable, Mapping

# The experience qualifier an Experienced or Inexperienced keyword prints: a level, a set code, or
# both, and never the alternate title some of them carry ("Experienced 2 Shinjo Yokatsu").
_EXPERIENCE = re.compile(r"(?:In)?[Ee]xperienced(?: ?\d+(?:\.\d+)?)?(?:KYD|CW|CoM)?")
EXPERIENCE_SEPARATOR = " • "
SUBTITLE_SEPARATOR = ", "


def card_slug(text: str) -> str:
    """Slug used as the card id when the YAML entry carries no explicit `id`."""
    s = text.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def experience_label(keywords: Iterable[str]) -> str | None:
    """The experience qualifier among ``keywords``, such as "Experienced 2KYD", or None for a card
    printing no Experienced or Inexperienced keyword."""
    for keyword in keywords:
        if match := _EXPERIENCE.match(keyword):
            return match.group()
    return None


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
    title = entry["title"]
    if subtitle := entry.get("subtitle"):
        title = f"{title}{SUBTITLE_SEPARATOR}{subtitle}"
    if label := experience_label(entry.get("keywords") or ()):
        title = f"{title}{EXPERIENCE_SEPARATOR}{label}"
    return title


def card_id(entry: Mapping) -> str:
    """The id of the card ``entry`` prints: its explicit ``id``, or the slug of its extended title,
    with ``__back`` appended for the reverse face of a double-faced card."""
    base = entry.get("id") or card_slug(extended_title(entry))
    return f"{base}__back" if entry.get("is_back") else base


def name_index[R: Mapping](records: Iterable[R]) -> dict[str, R]:
    """Index card records by the slugs a decklist name resolves through.

    A deck file names a card by the extended title it showed when the deck was written, and that
    slugs to the card's id unless a later reprint added a subtitle to the title the card shows. Ids
    are keyed first, then the slug of each card's current extended title, so an id always wins.

    Parameters
    ----------
    records : iterable of mapping
        Card records, each carrying ``card_id``, ``name`` and optionally ``extended_title``.

    Returns
    -------
    dict mapping str to mapping
        Slug to card record, for :func:`resolve_name`.
    """
    records = list(records)
    index = {record["card_id"]: record for record in records}
    for record in records:
        index.setdefault(card_slug(record.get("extended_title") or record["name"]), record)
    return index


def resolve_name[R](index: Mapping[str, R], name: str) -> R | None:
    """The record a decklist ``name`` names in ``index``, or None for a name no card answers to."""
    return index.get(card_slug(name))
