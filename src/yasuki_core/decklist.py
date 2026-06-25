import re

_COUNT_PREFIX = re.compile(r"^(\d+)[x×]\s+", re.IGNORECASE)
_SET_SUFFIX = re.compile(r"^(.*?)\s+\[([^\]]+)\]\s*$")
_ART_TRAILER = re.compile(r"\s*\{art:\s*(.+?)\}\s*$")


def parse_deck_yaml(text: str) -> dict:
    """
    Parse a YAML decklist into structured data.

    Lenient: unrecognized lines are ignored rather than raising, so malformed input yields a result
    whose section lists are empty rather than an exception.

    Parameters
    ----------
    text : str
        YAML decklist content, in the deck-builder export format.

    Returns
    -------
    parsed : dict
        Keys ``name`` (str), ``author`` (str), ``date`` (str), and the section lists ``pre_game``,
        ``dynasty``, ``fate``. Each section entry is a dict with ``name`` (str), ``count`` (int),
        ``set_name`` (str or None), and ``art`` (dict or None).
    """
    result = {
        "name": "Imported Deck",
        "author": "",
        "date": "",
        "pre_game": [],
        "dynasty": [],
        "fate": [],
    }
    current_section = None

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue

        meta_match = re.match(r"^(name|author):\s*(.+)$", trimmed)
        if meta_match:
            val = meta_match.group(2).strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            result[meta_match.group(1)] = val
            continue

        date_match = re.match(r"^date:\s*(.+)$", trimmed)
        if date_match:
            result["date"] = date_match.group(1).strip()
            continue

        # Accept the pretty keys (Dynasty:, Fate:, Pre-Game:) and the old lowercase ones.
        section_match = re.match(
            r"^(pre[-_ ]?game|dynasty|fate):\s*(#.*)?$", trimmed, re.IGNORECASE
        )
        if section_match:
            norm = re.sub(r"[-_ ]", "", section_match.group(1).lower())
            current_section = "pre_game" if norm == "pregame" else norm
            continue

        if current_section and re.match(r"^\s*-\s", line):
            entry = _parse_card_line(re.sub(r"^-\s*", "", trimmed))
            if entry:
                result[current_section].append(entry)

    return result


def _parse_card_line(text: str) -> dict | None:
    count = 1
    rest = text

    count_match = _COUNT_PREFIX.match(rest)
    if count_match:
        count = int(count_match.group(1))
        rest = rest[count_match.end() :]

    art = None
    art_match = _ART_TRAILER.search(rest)
    if art_match:
        art = _split_name_and_set(art_match.group(1).strip())
        rest = rest[: art_match.start()]

    parsed = _split_name_and_set(rest)
    if not parsed["name"]:
        return None
    return {"name": parsed["name"], "count": count, "set_name": parsed["set_name"], "art": art}


def _split_name_and_set(text: str) -> dict:
    set_match = _SET_SUFFIX.match(text)
    if set_match:
        return {"name": set_match.group(1).strip(), "set_name": set_match.group(2)}
    return {"name": text.strip(), "set_name": None}
