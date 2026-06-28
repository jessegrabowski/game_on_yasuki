from dataclasses import dataclass

import psycopg

from yasuki_core.decklist import parse_deck_yaml

# The three deck sections, in display order. A section name is also the persisted ``side`` value, so
# the parser keys, the YAML headers, and the deck_cards.side check constraint stay in lockstep.
SIDES = ("pre_game", "dynasty", "fate")
_SECTION_LABEL = {"pre_game": "Pre-Game", "dynasty": "Dynasty", "fate": "Fate"}


@dataclass(frozen=True)
class DeckCard:
    """One normalized deck entry — a single (card, side, printing, art-variant) with its quantity.

    Mirrors a ``deck_cards`` row minus its surrogate and ``deck_id``. ``card_name`` is the
    denormalized recovery handle stored alongside the id so an entry survives a card_id drift; the
    art-swap fields capture a borrowed printing semantically (donor card slug + set), never the
    builder's volatile synthetic print_id.
    """

    card_id: str
    card_name: str
    side: str
    quantity: int
    set_name: str | None = None
    art_donor_card_id: str | None = None
    art_donor_set: str | None = None


@dataclass(frozen=True)
class DeckSummary:
    """The denormalized summary the deck-tile / lobby list renders without joining deck_cards."""

    stronghold_card_id: str | None
    clan: str | None
    dynasty_count: int
    fate_count: int


class UnknownCardError(ValueError):
    """A deck references cards absent from the card database.

    The app-enforced integrity the separate-database design requires: with no cross-DB foreign key,
    every card a deck names is validated here at save time rather than by Postgres.
    """

    def __init__(self, unknown: list[str]):
        self.unknown = unknown
        super().__init__(f"Unknown cards: {', '.join(unknown)}")


def _display_name(record: dict) -> str:
    return record.get("extended_title") or record["name"]


def build_name_index(records: list[dict]) -> dict[str, dict]:
    """Index card records by lowercased name and extended title, the keys a decklist resolves by.

    Mirrors how ``get_cards_by_names`` matches, so a name written either way resolves to the same
    record.

    Parameters
    ----------
    records : list of dict
        Card records, each carrying ``card_id``, ``name``, and optionally ``extended_title``.

    Returns
    -------
    index : dict mapping str to dict
        Lowercased name and extended title both mapping to their record.
    """
    index: dict[str, dict] = {}
    for record in records:
        index[record["name"].lower()] = record
        extended = record.get("extended_title")
        if extended:
            index[extended.lower()] = record
    return index


def resolve_deck_cards(parsed: dict, name_index: dict[str, dict]) -> list[DeckCard]:
    """Resolve a parsed name-based decklist into validated, id-based deck cards.

    This is both the save-time serializer and its validation: every named card (and every art-swap
    donor) is looked up in ``name_index``, and any that miss are collected and raised together so a
    user sees every problem at once. Identical entries — same card, side, printing, and art
    variant — are summed into one row, matching the null-safe uniqueness the schema enforces.

    Parameters
    ----------
    parsed : dict
        The output of ``parse_deck_yaml``: ``pre_game`` / ``dynasty`` / ``fate`` lists of entries,
        each ``{name, count, set_name, art}`` where ``art`` is ``{name, set_name}`` or None.
    name_index : dict mapping str to dict
        Lowercased name/title to card record, as built by ``build_name_index``.

    Returns
    -------
    cards : list of DeckCard
        One entry per distinct variant, in first-seen order.

    Raises
    ------
    UnknownCardError
        If any named card or donor is absent from ``name_index``.
    """
    unknown: list[str] = []
    quantities: dict[tuple, int] = {}
    names: dict[tuple, str] = {}
    order: list[tuple] = []

    for side in SIDES:
        for entry in parsed.get(side, []):
            record = name_index.get(entry["name"].lower())
            if record is None:
                unknown.append(entry["name"])
                continue
            donor_id = donor_set = None
            art = entry.get("art")
            if art:
                donor = name_index.get(art["name"].lower())
                if donor is None:
                    unknown.append(art["name"])
                    continue
                donor_id, donor_set = donor["card_id"], art.get("set_name")
            key = (record["card_id"], side, entry.get("set_name"), donor_id, donor_set)
            if key not in quantities:
                order.append(key)
                names[key] = _display_name(record)
            quantities[key] = quantities.get(key, 0) + entry["count"]

    if unknown:
        raise UnknownCardError(unknown)

    cards = []
    for key in order:
        card_id, side, set_name, donor_id, donor_set = key
        cards.append(
            DeckCard(
                card_id=card_id,
                card_name=names[key],
                side=side,
                quantity=quantities[key],
                set_name=set_name,
                art_donor_card_id=donor_id,
                art_donor_set=donor_set,
            )
        )
    return cards


def assert_card_ids_known(cards: list[DeckCard], known_ids: set[str]) -> None:
    """Raise ``UnknownCardError`` if any card or art-swap donor is not a real card id.

    The id-based twin of ``resolve_deck_cards``' validation, for a deck that already carries card
    ids (a re-save, or a builder payload that skipped the name round-trip).

    Parameters
    ----------
    cards : list of DeckCard
        The deck to validate.
    known_ids : set of str
        Every valid card id, e.g. from ``database.all_card_ids``.
    """
    referenced: set[str] = set()
    for card in cards:
        referenced.add(card.card_id)
        if card.art_donor_card_id:
            referenced.add(card.art_donor_card_id)
    unknown = sorted(referenced - known_ids)
    if unknown:
        raise UnknownCardError(unknown)


def summarize(cards: list[DeckCard], records_by_id: dict[str, dict]) -> DeckSummary:
    """Derive the denormalized deck summary from its cards.

    The stronghold is the pre-game card typed ``Stronghold``; the deck's clan is that stronghold's
    clan. Dynasty and fate counts sum the quantities on their sides.

    Parameters
    ----------
    cards : list of DeckCard
        The deck's resolved entries.
    records_by_id : dict mapping str to dict
        Card id to record, supplying ``types`` and ``clans`` for the stronghold lookup.

    Returns
    -------
    summary : DeckSummary
        Stronghold id, clan, and dynasty/fate counts; the stronghold and clan are None if the deck
        has no stronghold.
    """
    stronghold_id: str | None = None
    clan: str | None = None
    dynasty_count = fate_count = 0
    for card in cards:
        if card.side == "dynasty":
            dynasty_count += card.quantity
        elif card.side == "fate":
            fate_count += card.quantity
        if stronghold_id is None and card.side == "pre_game":
            record = records_by_id.get(card.card_id)
            if record and "Stronghold" in (record.get("types") or []):
                stronghold_id = card.card_id
                clans = record.get("clans") or []
                clan = clans[0] if clans else None
    return DeckSummary(stronghold_id, clan, dynasty_count, fate_count)


def to_rows(cards: list[DeckCard], deck_id: int) -> list[dict]:
    """The ``deck_cards`` insert dicts for a deck's cards, keyed to ``deck_id``."""
    return [
        {
            "deck_id": deck_id,
            "card_id": card.card_id,
            "card_name": card.card_name,
            "set_name": card.set_name,
            "side": card.side,
            "quantity": card.quantity,
            "art_donor_card_id": card.art_donor_card_id,
            "art_donor_set": card.art_donor_set,
        }
        for card in cards
    ]


def from_rows(rows: list[dict]) -> list[DeckCard]:
    """The deck cards reconstructed from ``deck_cards`` rows."""
    return [
        DeckCard(
            card_id=row["card_id"],
            card_name=row["card_name"],
            side=row["side"],
            quantity=row["quantity"],
            set_name=row["set_name"],
            art_donor_card_id=row["art_donor_card_id"],
            art_donor_set=row["art_donor_set"],
        )
        for row in rows
    ]


def to_yaml(
    cards: list[DeckCard],
    *,
    name: str = "Untitled Deck",
    author: str | None = None,
    date: str | None = None,
    donor_names: dict[str, str] | None = None,
) -> str:
    """Serialize deck cards to the interchange YAML ``parse_deck_yaml`` reads back.

    Within each section cards sort by name then set for a stable export. An art-swap renders as the
    ``{art: Donor [Set]}`` trailer; the donor's display name comes from ``donor_names`` (its slug is
    a graceful fallback), since the row stores only the donor's id.

    Parameters
    ----------
    cards : list of DeckCard
        The deck to write.
    name : str, optional
        The deck name for the ``name:`` line. Default 'Untitled Deck'.
    author : str, optional
        Written as an ``author:`` line when given. Default None.
    date : str, optional
        Written as a ``date:`` line when given. Default None.
    donor_names : dict mapping str to str, optional
        Art-swap donor card id to display name. Default None (donors render by id).

    Returns
    -------
    yaml : str
        The decklist text, newline-terminated.
    """
    donor_names = donor_names or {}
    lines = [f"name: {name}"]
    if author:
        lines.append(f"author: {author}")
    if date:
        lines.append(f"date: {date}")

    for side in SIDES:
        section = sorted(
            (card for card in cards if card.side == side),
            key=lambda card: (card.card_name.lower(), card.set_name or ""),
        )
        if not section:
            continue
        lines.append("")
        lines.append(f"{_SECTION_LABEL[side]}:")
        for card in section:
            count = f"{card.quantity}x " if card.quantity > 1 else ""
            set_suffix = f" [{card.set_name}]" if card.set_name else ""
            art_suffix = ""
            if card.art_donor_card_id:
                donor = donor_names.get(card.art_donor_card_id, card.art_donor_card_id)
                donor_set = f" [{card.art_donor_set}]" if card.art_donor_set else ""
                art_suffix = f" {{art: {donor}{donor_set}}}"
            lines.append(f"  - {count}{card.card_name}{set_suffix}{art_suffix}")

    return "\n".join(lines) + "\n"


def deck_from_yaml(text: str, name_index: dict[str, dict]) -> list[DeckCard]:
    """Parse and resolve a YAML decklist in one step — the import-and-validate entry point."""
    return resolve_deck_cards(parse_deck_yaml(text), name_index)


def stored_card_ids(conn: psycopg.Connection) -> set[str]:
    """Every card id referenced by any stored deck — cards and art-swap donors alike."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT card_id FROM deck_cards "
            "UNION "
            "SELECT art_donor_card_id FROM deck_cards WHERE art_donor_card_id IS NOT NULL"
        )
        return {row["card_id"] for row in cur.fetchall()}


def orphan_card_ids(stored_ids: set[str], known_ids: set[str]) -> set[str]:
    """The stored card ids absent from the card database — the post-rebuild integrity sweep.

    A non-empty result means a card-DB rebuild dropped or renamed an id some deck still references;
    those decks need re-linking (by the denormalized ``card_name``) before the id vanishes for good.

    Parameters
    ----------
    stored_ids : set of str
        Card ids referenced by stored decks, e.g. from ``stored_card_ids``.
    known_ids : set of str
        Every valid card id, e.g. from ``database.all_card_ids``.

    Returns
    -------
    orphans : set of str
        Ids in ``stored_ids`` but not in ``known_ids``.
    """
    return stored_ids - known_ids
