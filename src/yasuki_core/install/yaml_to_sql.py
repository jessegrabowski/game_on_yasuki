import datetime
import logging
import re
import sys
from pathlib import Path
from typing import NamedTuple

import psycopg
import yaml
from psycopg.types.json import Json

from yasuki_core.install.format_metadata import populate_format_metadata
from yasuki_core.install.sets_to_sql import coerce_date
from yasuki_core.install.utils import normalize_name

logger = logging.getLogger(__name__)

# YAML stat field == card column name. A value that is a clean integer fills the column; a meaningful
# non-integer (a follower modifier like "+2", a variable "*") is kept under "<col>_raw" in extra.
STAT_FIELDS = (
    "gold_cost",
    "focus",
    "force",
    "chi",
    "honor_requirement",
    "personal_honor",
    "province_strength",
    "starting_honor",
    "gold_production",
)


def card_slug(text: str) -> str:
    """Slug used as the card id when the YAML entry carries no explicit `id`."""
    s = text.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def parse_collector_numbers(raw: str | None) -> list[tuple[str | None, int]]:
    """Split a collector-number string into (subset, number) pairs, in order."""
    if not raw:
        return []
    entries: list[tuple[str | None, int]] = []
    for part in (p.strip() for p in raw.split(",")):
        m = re.match(r"^([A-Za-z ]*?)\s*([0-9]+)$", part)
        if m:
            entries.append((m.group(1).strip() or None, int(m.group(2))))
    return entries


# Cards-table column order. The row _card_columns builds matches it positionally, and the INSERT is
# generated from it, so the back_card_id position the link pass writes to is derived here rather than
# hand-counted.
_CARD_COLUMN_NAMES = (
    "card_id",
    "slug",
    "name",
    "extended_title",
    "name_normalized",
    "rules_text",
    "gold_cost",
    "focus",
    "force",
    "chi",
    "honor_requirement",
    "personal_honor",
    "province_strength",
    "starting_honor",
    "gold_production",
    "back_card_id",
    "is_back",
    "is_unique",
    "is_proxy",
    "is_banned",
    "errata_text",
    "story",
    "notes",
    "extra",
    "experience",
)
_BACK_CARD_ID_COL = _CARD_COLUMN_NAMES.index("back_card_id")
_RULES_TEXT_COL = _CARD_COLUMN_NAMES.index("rules_text")
_STAT_COL = {col: _CARD_COLUMN_NAMES.index(col) for col in STAT_FIELDS}


class CardRevision(NamedTuple):
    revision_index: int
    effective_date: datetime.date | None
    source: str | None
    source_url: str | None
    rules_text: str
    stats: dict[str, int]
    image_path: str | None
    notes: str | None


def build_revisions(original_text: str, errata: list[dict]) -> list[CardRevision]:
    """Build a card's ordered revision list from its original rules text and its errata entries.

    Each errata entry is a dict with ``date`` and ``text``, optionally ``source``, ``source_url``,
    ``art`` and ``set_slug`` (which resolve the revision's image path), ``notes``, and any integer
    stat overrides keyed by stat column. Revision 0 is the original text; errata follow sorted by
    effective date, so the last element is the current version.

    Parameters
    ----------
    original_text : str
        The card's pre-errata rules text.
    errata : list of dict
        The errata entries collected for the card, in any order.

    Returns
    -------
    revisions : list of CardRevision
        Revisions ordered oldest to newest, with the original at index 0.

    Raises
    ------
    ValueError
        If an errata entry has a missing or unparseable ``date``. Unlike an original printing, an
        erratum without a datable effective date is a data error, not a legitimate null.
    """
    dated = []
    for entry in errata:
        date = coerce_date(entry.get("date"))
        if date is None:
            raise ValueError(
                f"Errata entry has a missing or unparseable date {entry.get('date')!r}: "
                f"{entry.get('text', '')[:60]!r}"
            )
        dated.append((date, entry))
    dated.sort(key=lambda pair: pair[0])

    revisions = [CardRevision(0, None, None, None, original_text, {}, None, None)]
    for index, (date, entry) in enumerate(dated, start=1):
        stats = {col: entry[col] for col in STAT_FIELDS if isinstance(entry.get(col), int)}
        art = entry.get("art")
        image_path = f"sets/{entry['set_slug']}/{art}" if art else None
        revisions.append(
            CardRevision(
                index,
                date,
                entry.get("source"),
                entry.get("source_url"),
                entry["text"],
                stats,
                image_path,
                entry.get("notes"),
            )
        )
    return revisions


def _revision_baseline(errata: list[dict], fallback: str) -> str:
    """The pre-errata text for revision 0: the ``home_text`` of the oldest erratum — the text on the
    printing that erratum was issued for — so the compare diffs against the right prior wording even
    when that printing is not the card's first-seen entry. Falls back to ``fallback`` when the oldest
    erratum carries no home text."""
    oldest = min(errata, key=lambda e: coerce_date(e.get("date")) or datetime.date.min)
    return oldest.get("home_text") or fallback


def _apply_current_revision(row: list, revisions: list[CardRevision]) -> None:
    """Mutate a cards row so its rules text and stats reflect the newest revision. Stat overrides
    accumulate in date order, so a stat an earlier errata changed sticks until a later one changes it
    again."""
    row[_RULES_TEXT_COL] = revisions[-1].rules_text
    for revision in revisions[1:]:
        for col, value in revision.stats.items():
            row[_STAT_COL[col]] = value


def _experience_level(extended_title: str) -> int:
    """Rank a personality's experience version for ordering within a name: Inexperienced (-1), base
    (0), Experienced (1), Experienced 2 (2), ... A set-code variant (e.g. 'Experienced 2CW') shares
    its number's rank."""
    lowered = extended_title.lower()
    if "inexperienced" in lowered:
        return -1
    match = re.search(r"experienced\s*(\d*)", lowered)
    if match:
        return int(match.group(1)) if match.group(1) else 1
    return 0


def _card_columns(card_id: str, extended_title: str, entry: dict) -> tuple[list, dict]:
    """Build the cards-table row for an entry, plus the `extra` payload for non-integer stats."""
    title = entry["title"]
    extra: dict[str, str] = {}
    stats: dict[str, int | None] = {}
    for col in STAT_FIELDS:
        value = entry.get(col)
        if isinstance(value, int):
            stats[col] = value
        else:
            stats[col] = None
            if value is not None:
                extra[f"{col}_raw"] = str(value)
    row = [
        card_id,
        card_slug(extended_title),
        title,
        extended_title,
        normalize_name(title),
        entry.get("text", "") or "",
        stats["gold_cost"],
        stats["focus"],
        stats["force"],
        stats["chi"],
        stats["honor_requirement"],
        stats["personal_honor"],
        stats["province_strength"],
        stats["starting_honor"],
        stats["gold_production"],
        None,  # back_card_id — filled in by _link_and_validate_back_faces
        bool(entry.get("is_back")),
        bool(entry.get("is_unique")),
        bool(entry.get("is_proxy")),
        bool(entry.get("is_banned")),
        entry.get("errata_text"),
        entry.get("story"),
        entry.get("notes"),
        Json(extra),
        _experience_level(extended_title),
    ]
    return row, extra


def _link_and_validate_back_faces(cards: dict, card_names: dict, back_ids: set) -> None:
    """Point each front row at its back face. Every is_back card must have a front (is_back=False)
    card of the same name — the link is derived from that shared name, so its absence is a fatal
    data error, not something to paper over."""
    front_names = {card_names[c] for c in cards if c not in back_ids}
    for back_id in back_ids:
        name = card_names[back_id]
        if name not in front_names:
            raise ValueError(
                f"Back-face card {back_id!r} ({name!r}) has no front (is_back=False) card "
                "of the same name"
            )
        front_id = back_id.removesuffix("__back")
        if front_id not in cards:
            raise ValueError(f"Back-face card {back_id!r} has no front card {front_id!r}")
        cards[front_id][_BACK_CARD_ID_COL] = back_id


def mrp_text(dated_texts: list[tuple[datetime.date | None, str]]) -> str | None:
    """The rules text from the most-recently-released printing (the MRP standard). Each element is a
    ``(release_date, text)`` pair for one printing that carries text; a null date sorts oldest so a
    dated printing always wins over an undated one. Return None for an empty list.

    Parameters
    ----------
    dated_texts : list of tuple of (date or None, str)
        One ``(release_date, text)`` pair per printing of the card that has non-empty text.

    Returns
    -------
    text : str or None
        The text on the newest printing, or None if there are no printings.
    """
    if not dated_texts:
        return None
    return max(dated_texts, key=lambda dt: dt[0] or datetime.date.min)[1]


def load_cards(cards_dir: Path, dsn: str) -> None:
    """
    Load every per-set YAML file into the card tables.

    Cards are identified by their explicit `id` or, failing that, a slug of the extended title, and
    deduplicated across the sets they appear in. Each YAML entry contributes one printing; a card with
    several printings in one set gets suffixed printing ids. Set names resolve to set ids via l5r_sets.

    Parameters
    ----------
    cards_dir : path
        Directory of per-set YAML files.
    dsn : str
        PostgreSQL connection string.
    """
    yaml_files = sorted(cards_dir.glob("*.yaml"))
    if not yaml_files:
        raise ValueError(f"No YAML files found in {cards_dir}")

    cards: dict[str, list] = {}
    card_names: dict[str, str] = {}
    back_ids: set[str] = set()
    clan_links: set[tuple[str, str]] = set()
    type_links: set[tuple[str, str]] = set()
    deck_links: set[tuple[str, str]] = set()
    keywords: set[str] = set()
    keyword_links: set[tuple[str, str]] = set()
    formats: set[str] = set()
    legality_links: set[tuple[str, str]] = set()
    print_rows: list[tuple] = []
    number_map: dict[tuple[str, str], list[tuple[str | None, int]]] = {}
    # Errata are collected across every entry of a card, keyed by card_id, so which per-set file a
    # card's canonical row happens to come from (filename sort order) never decides which errata win.
    errata_map: dict[str, list[dict]] = {}

    # The Most-Recent-Printing standard: a card's standing rules text is the text on its newest
    # printing, not whichever set file happens to sort first. Collect every printing's text per card
    # and fold the most recent onto the card row once every file is read.
    latest_text: dict[str, list[tuple[datetime.date | None, str]]] = {}

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_name, set_id, set_slug, release_date FROM l5r_sets")
        set_map = {name: (set_id, slug, date) for name, set_id, slug, date in cur.fetchall()}

        for yaml_file in yaml_files:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            set_name = data["set"]
            resolved = set_map.get(set_name)
            if resolved is None:
                logger.warning("Set %r not in l5r_sets; skipping %s", set_name, yaml_file.name)
                continue
            set_id, set_slug, set_date = resolved

            printings_seen: dict[str, int] = {}
            for entry in data.get("cards", []):
                extended_title = entry.get("extended_title") or entry["title"]
                card_id = entry.get("id") or card_slug(extended_title)
                if entry.get("is_back"):
                    card_id += "__back"

                entry_text = entry.get("text")
                if entry_text:
                    latest_text.setdefault(card_id, []).append((set_date, entry_text))

                if card_id not in cards:
                    cards[card_id], _ = _card_columns(card_id, extended_title, entry)
                    card_names[card_id] = entry["title"]
                    if entry.get("is_back"):
                        back_ids.add(card_id)
                    clan_links.update((card_id, c) for c in entry.get("clans", []))
                    type_links.update((card_id, t) for t in entry.get("types", []))
                    deck_links.update((card_id, d) for d in entry.get("decks", []))
                    for kw in entry.get("keywords", []):
                        keywords.add(kw)
                        keyword_links.add((card_id, kw))
                    for fmt in entry.get("legality", []):
                        formats.add(fmt)
                        legality_links.add((card_id, fmt))

                for erratum in entry.get("errata", []):
                    errata_map.setdefault(card_id, []).append(
                        {**erratum, "set_slug": set_slug, "home_text": entry.get("text", "") or ""}
                    )

                n = printings_seen.get(card_id, 0)
                printings_seen[card_id] = n + 1
                printing_id = set_slug if n == 0 else f"{set_slug}_{n + 1}"
                collector = entry.get("collector_number")
                print_rows.append(
                    (
                        card_id,
                        printing_id,
                        set_id,
                        entry.get("rarity"),
                        entry.get("flavor_text"),
                        entry.get("back_title"),
                        entry.get("back_flavor"),
                        entry.get("artist"),
                        entry.get("designer"),
                        collector,
                        entry.get("publisher"),
                        entry.get("publisher_url"),
                        bool(entry.get("doublesided")),
                        coerce_date(entry.get("legal_date")),
                    )
                )
                number_map[(card_id, printing_id)] = parse_collector_numbers(collector)

        _link_and_validate_back_faces(cards, card_names, back_ids)

        # Set each card's standing rules text to its most-recent printing (MRP standard). This runs
        # before errata folding so an erratum, being the newest revision, still wins over the printing.
        for card_id, dated_texts in latest_text.items():
            text = mrp_text(dated_texts)
            if text is not None and card_id in cards:
                cards[card_id][_RULES_TEXT_COL] = text

        # Fold each errata'd card's newest revision onto its cards row so every existing read path
        # serves the current text/stats, and stage the full ordered history for card_revisions.
        revision_rows: list[tuple] = []
        for card_id, entries in errata_map.items():
            baseline = _revision_baseline(entries, cards[card_id][_RULES_TEXT_COL])
            revisions = build_revisions(baseline, entries)
            _apply_current_revision(cards[card_id], revisions)
            for rev in revisions:
                revision_rows.append(
                    (
                        card_id,
                        rev.revision_index,
                        rev.effective_date,
                        rev.source,
                        rev.source_url,
                        rev.rules_text,
                        Json(rev.stats),
                        rev.image_path,
                        rev.notes,
                    )
                )

        _insert_all(
            cur,
            cards,
            clan_links,
            type_links,
            deck_links,
            keywords,
            keyword_links,
            formats,
            legality_links,
            print_rows,
            number_map,
            revision_rows,
        )
        conn.commit()

    logger.info(
        "Loaded %d cards, %d printings, %d revisions from %d sets",
        len(cards),
        len(print_rows),
        len(revision_rows),
        len(yaml_files),
    )


def _insert_all(
    cur,
    cards,
    clan_links,
    type_links,
    deck_links,
    keywords,
    keyword_links,
    formats,
    legality_links,
    print_rows,
    number_map,
    revision_rows,
) -> None:
    """Batch-insert the accumulated rows in dependency order, then resolve print numbers."""
    cur.executemany(
        "INSERT INTO formats (name) VALUES (%s) ON CONFLICT DO NOTHING", [(f,) for f in formats]
    )
    cur.executemany(
        "INSERT INTO keywords (keyword) VALUES (%s) ON CONFLICT DO NOTHING",
        [(k,) for k in keywords],
    )
    columns = ", ".join(_CARD_COLUMN_NAMES)
    placeholders = ", ".join(["%s"] * len(_CARD_COLUMN_NAMES))
    cur.executemany(
        f"""
        INSERT INTO cards ({columns}) VALUES ({placeholders})
        ON CONFLICT (card_id) DO NOTHING
        """,
        list(cards.values()),
    )
    cur.executemany(
        """
        INSERT INTO card_revisions
          (card_id, revision_index, effective_date, source, source_url, rules_text, stats, image_path, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (card_id, revision_index) DO NOTHING
        """,
        revision_rows,
    )
    cur.executemany(
        "INSERT INTO card_clans (card_id, clan) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        list(clan_links),
    )
    cur.executemany(
        "INSERT INTO card_card_types (card_id, type) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        list(type_links),
    )
    cur.executemany(
        "INSERT INTO card_decks (card_id, deck) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        list(deck_links),
    )
    cur.executemany(
        "INSERT INTO card_keywords (card_id, keyword) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        list(keyword_links),
    )
    cur.executemany(
        "INSERT INTO card_legalities (card_id, format_name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        list(legality_links),
    )

    cur.executemany(
        """
        INSERT INTO prints (
          card_id, printing_id, set_id, rarity, flavor_text, back_title, back_flavor, artist, designer,
          collector_number_raw, publisher, publisher_url, doublesided, legal_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (card_id, printing_id) DO NOTHING
        """,
        print_rows,
    )
    cur.execute("SELECT print_id, card_id, printing_id FROM prints")
    print_ids = {
        (card_id, printing_id): print_id for print_id, card_id, printing_id in cur.fetchall()
    }
    affected = [print_ids[key] for key in number_map if key in print_ids]
    number_rows = [
        (print_ids[key], subset, value, position)
        for key, numbers in number_map.items()
        if key in print_ids
        for position, (subset, value) in enumerate(numbers)
    ]
    # print_numbers has no natural key, so a plain insert would duplicate every row on re-run.
    # Clear these prints' numbers first so the load stays idempotent (it re-runs on each deploy).
    if affected:
        cur.execute("DELETE FROM print_numbers WHERE print_id = ANY(%s)", (affected,))
    if number_rows:
        cur.executemany(
            "INSERT INTO print_numbers (print_id, subset, number_int, position) "
            "VALUES (%s, %s, %s, %s)",
            number_rows,
        )

    # Sets are already loaded, so each format's arc and chronological legal_from can be resolved now.
    populate_format_metadata(cur)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_cards(Path(sys.argv[1]), sys.argv[2])
