import re

YAML_SECTIONS = [
    ("pre_game", "SETUP"),
    ("dynasty", "DYNASTY"),
    ("fate", "FATE"),
]

_NEEDS_QUOTE = re.compile(r"[:#\[\]{},&*?|<>=!%@`]")
_COUNT_PREFIX = re.compile(r"^(\d+)[x×]\s+", re.IGNORECASE)
_SET_SUFFIX = re.compile(r"^(.*?)\s+\[([^\]]+)\]\s*$")


def serialize_deck(
    deck_state,
    repository,
    deck_name: str = "",
) -> str:
    """
    Serialize a DeckState to the portable YAML decklist format.

    Parameters
    ----------
    deck_state : DeckState
        Current deck composition
    repository : DeckBuilderRepository
        Card data lookup
    deck_name : str
        Deck name to embed in the file

    Returns
    -------
    yaml : str
        YAML-formatted decklist
    """
    lines = [f"name: {_quote_value(deck_name)}", ""]

    cards_by_id = repository.cards_by_id

    for section_key, side in YAML_SECTIONS:
        entries = _collect_side_entries(deck_state, cards_by_id, repository, side)
        if not entries:
            continue

        lines.append(f"{section_key}:")
        for display_name, set_name, count in sorted(entries):
            count_prefix = f"{count}x " if count > 1 else ""
            set_suffix = f" [{set_name}]" if set_name else ""
            lines.append(f"  - {count_prefix}{display_name}{set_suffix}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _collect_side_entries(deck_state, cards_by_id, repository, side):
    entries = []
    for card_id, print_list in deck_state.cards.items():
        card = cards_by_id.get(card_id)
        if not card:
            continue

        card_side = card.get("side")
        if side == "SETUP":
            if card_side in ("FATE", "DYNASTY"):
                continue
        elif card_side != side:
            continue

        display_name = card.get("extended_title") or card.get("name", card_id)

        for print_id, count in print_list:
            prints = repository.get_prints(card_id)
            print_info = next((p for p in prints if p["print_id"] == print_id), None)
            set_name = print_info.get("set_name") if print_info else None
            entries.append((display_name, set_name, count))

    return entries


def parse_deck_yaml(text: str) -> dict:
    """
    Parse a YAML decklist into structured data.

    Parameters
    ----------
    text : str
        YAML decklist content

    Returns
    -------
    parsed : dict
        Keys: ``name`` (str), ``pre_game`` (list), ``dynasty`` (list),
        ``fate`` (list). Each list contains dicts with ``name`` (str),
        ``count`` (int), ``set_name`` (str or None).
    """
    result = {"name": "Imported Deck", "pre_game": [], "dynasty": [], "fate": []}
    current_section = None

    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue

        name_match = re.match(r"^name:\s*(.+)$", trimmed)
        if name_match:
            val = name_match.group(1).strip()
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
            result["name"] = val
            continue

        section_match = re.match(r"^(pre_game|dynasty|fate):\s*$", trimmed)
        if section_match:
            current_section = section_match.group(1)
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

    set_name = None
    set_match = _SET_SUFFIX.match(rest)
    if set_match:
        rest = set_match.group(1)
        set_name = set_match.group(2)

    name = rest.strip()
    if not name:
        return None
    return {"name": name, "count": count, "set_name": set_name}


def import_deck_yaml(
    text: str,
    repository,
) -> tuple:
    """
    Import a YAML decklist into a DeckState.

    Resolves card names against the repository's local database.

    Parameters
    ----------
    text : str
        YAML decklist content
    repository : DeckBuilderRepository
        Card data lookup

    Returns
    -------
    result : tuple of (DeckState, str, list of str)
        (new deck state, deck name, list of unresolved card names)
    """
    from yasuki_gui.ui.deck_builder.deck_data import DeckState

    parsed = parse_deck_yaml(text)
    cards_by_ext = _build_name_index(repository)

    state = DeckState()
    unresolved = []

    section_sides = {"pre_game": None, "dynasty": "DYNASTY", "fate": "FATE"}

    for section, entries in [
        ("pre_game", parsed["pre_game"]),
        ("dynasty", parsed["dynasty"]),
        ("fate", parsed["fate"]),
    ]:
        expected_side = section_sides[section]

        for entry in entries:
            card, card_id = _resolve_card(entry["name"], cards_by_ext, expected_side, repository)
            if not card:
                unresolved.append(entry["name"])
                continue

            prints = repository.get_prints(card_id)
            matched_print = None
            if entry["set_name"]:
                matched_print = next(
                    (p for p in prints if p["set_name"] == entry["set_name"]), None
                )
            if not matched_print and prints:
                matched_print = prints[0]
            if not matched_print:
                unresolved.append(entry["name"])
                continue

            print_id = matched_print["print_id"]
            for _ in range(entry["count"]):
                state = state.add_card(card_id, print_id)

    return state, parsed["name"], unresolved


def _build_name_index(repository) -> dict[str, tuple[dict, str]]:
    """
    Build a case-insensitive name → (card, card_id) index.

    Keys by extended_title first, then name as fallback (no overwrite).
    """
    index: dict[str, tuple[dict, str]] = {}

    for card_id, card in repository.cards_by_id.items():
        key = (card.get("extended_title") or card.get("name", "")).lower()
        if key:
            index[key] = (card, card_id)

    for card_id, card in repository.cards_by_id.items():
        name_key = card.get("name", "").lower()
        if name_key and name_key not in index:
            index[name_key] = (card, card_id)

    return index


def _resolve_card(name, cards_by_ext, expected_side, repository):
    key = name.lower()
    result = cards_by_ext.get(key)
    if not result:
        return None, None
    return result


def _quote_value(s: str) -> str:
    if _NEEDS_QUOTE.search(s) or s.startswith(" ") or s.endswith(" "):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s
