import datetime
import re

from yasuki_core.card_art import CustomPrint
from yasuki_core.decklist import parse_deck_yaml
from yasuki_gui.ui.deck_builder.deck_data import card_in_side

YAML_SECTIONS = [
    ("pre_game", "SETUP"),
    ("dynasty", "DYNASTY"),
    ("fate", "FATE"),
]
SECTION_LABEL = {"pre_game": "Pre-Game", "dynasty": "Dynasty", "fate": "Fate"}


def _pluralize(word: str) -> str:
    """Title-case-preserving plural for type subheaders (Holding -> Holdings, Strategy -> Strategies)."""
    return word[:-1] + "ies" if word.endswith("y") else word + "s"


_NEEDS_QUOTE = re.compile(r"[:#\[\]{},&*?|<>=!%@`]")


def serialize_deck(
    deck_state,
    repository,
    deck_name: str = "",
    deck_author: str = "",
    today: str | None = None,
) -> str:
    """
    Serialize a DeckState to the portable YAML decklist format.

    Each deck section is grouped by card type with ``# Type (n)`` subheaders and counts (comments,
    skipped on import); name/author/date metadata heads the file.

    Parameters
    ----------
    deck_state : DeckState
        Current deck composition.
    repository : DeckBuilderRepository
        Card data lookup.
    deck_name : str
        Deck name to embed in the file. Default ''.
    deck_author : str
        Deck author; omitted from the file when empty. Default ''.
    today : str, optional
        ISO date for the ``date:`` line. Defaults to today.

    Returns
    -------
    yaml : str
        YAML-formatted decklist.
    """
    if today is None:
        today = datetime.date.today().isoformat()

    lines = [f"name: {_quote_value(deck_name)}"]
    if deck_author:
        lines.append(f"author: {_quote_value(deck_author)}")
    lines.append(f"date: {today}")
    lines.append("")

    cards_by_id = repository.cards_by_id

    for section_key, side in YAML_SECTIONS:
        entries = _collect_side_entries(deck_state, cards_by_id, repository, side)
        if not entries:
            continue

        by_type: dict[str, list] = {}
        for entry in entries:
            by_type.setdefault(entry[0], []).append(entry)

        lines.append(f"{SECTION_LABEL[section_key]}: # ({sum(e[4] for e in entries)})")
        for i, type_name in enumerate(sorted(by_type)):
            if i > 0:
                lines.append("")  # blank line between type blocks
            group = sorted(by_type[type_name], key=lambda e: (e[1], e[2] or "", e[3]))
            lines.append(f"  # {_pluralize(type_name)} ({sum(e[4] for e in group)})")
            for _type, display_name, set_name, art_suffix, count in group:
                count_prefix = f"{count}x " if count > 1 else ""
                set_suffix = f" [{set_name}]" if set_name else ""
                lines.append(f"  - {count_prefix}{display_name}{set_suffix}{art_suffix}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _collect_side_entries(deck_state, cards_by_id, repository, side):
    entries = []
    for card_id, print_list in deck_state.cards.items():
        card = cards_by_id.get(card_id)
        if not card:
            continue

        if not card_in_side(card, side):
            continue

        display_name = card.get("extended_title") or card.get("name", card_id)
        type_name = (card.get("types") or ["Other"])[0]

        for print_id, count in print_list:
            prints = repository.get_prints(card_id)
            print_info = next((p for p in prints if p["print_id"] == print_id), None)
            if print_info and print_info.get("is_custom"):
                set_name, art_suffix = _custom_entry_suffix(print_info["recipe"], repository)
            else:
                set_name = print_info.get("set_name") if print_info else None
                art_suffix = ""
            entries.append((type_name, display_name, set_name, art_suffix, count))

    return entries


def _custom_entry_suffix(recipe, repository):
    """Return (recipient set name, ``{art: ...}`` suffix) for a custom-print recipe."""
    recipient_set = _set_name_for_print(
        repository, recipe.recipient_card_id, recipe.recipient_print_id
    )

    donor = repository.get_card(recipe.donor_card_id) or {}
    donor_name = donor.get("extended_title") or donor.get("name", recipe.donor_card_id)
    donor_set = _set_name_for_print(repository, recipe.donor_card_id, recipe.donor_print_id)
    donor_ref = f"{donor_name} [{donor_set}]" if donor_set else donor_name
    return recipient_set, f" {{art: {donor_ref}}}"


def _set_name_for_print(repository, card_id, print_id):
    for p in repository.get_prints(card_id):
        if p["print_id"] == print_id and not p.get("is_custom"):
            return p.get("set_name")
    return None


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
    result : tuple of (DeckState, str, str, list of str)
        (new deck state, deck name, deck author, list of unresolved card names)
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
            if entry.get("art"):
                custom_id = _resolve_custom_print(
                    card_id, print_id, entry["art"], cards_by_ext, repository
                )
                if custom_id is not None:
                    print_id = custom_id
                else:
                    unresolved.append(entry["art"]["name"])

            for _ in range(entry["count"]):
                state = state.add_card(card_id, print_id)

    return state, parsed["name"], parsed["author"], unresolved


def _resolve_custom_print(recipient_card_id, recipient_print_id, art, cards_by_ext, repository):
    """Register the art-swap recipe for an ``{art: ...}`` entry; return its id or None if unresolved."""
    donor = cards_by_ext.get(art["name"].lower())
    if not donor:
        return None
    _, donor_card_id = donor

    donor_prints = repository.get_prints(donor_card_id)
    donor_print = None
    if art["set_name"]:
        donor_print = next((p for p in donor_prints if p["set_name"] == art["set_name"]), None)
    if not donor_print and donor_prints:
        donor_print = donor_prints[0]
    if not donor_print:
        return None

    recipe = CustomPrint(
        recipient_card_id, recipient_print_id, donor_card_id, donor_print["print_id"]
    )
    return repository.register_custom_print(recipe)


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
