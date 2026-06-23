import logging
import re
import sys
from pathlib import Path

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


# Index of back_card_id in the row built by _card_columns; the link pass fills it in afterwards.
_BACK_CARD_ID_COL = 15


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

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT set_name, set_id, set_slug FROM l5r_sets")
        set_map = {name: (set_id, slug) for name, set_id, slug in cur.fetchall()}

        for yaml_file in yaml_files:
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            set_name = data["set"]
            resolved = set_map.get(set_name)
            if resolved is None:
                logger.warning("Set %r not in l5r_sets; skipping %s", set_name, yaml_file.name)
                continue
            set_id, set_slug = resolved

            printings_seen: dict[str, int] = {}
            for entry in data.get("cards", []):
                extended_title = entry.get("extended_title") or entry["title"]
                card_id = entry.get("id") or card_slug(extended_title)
                if entry.get("is_back"):
                    card_id += "__back"

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
        )
        conn.commit()

    logger.info(
        "Loaded %d cards, %d printings from %d sets", len(cards), len(print_rows), len(yaml_files)
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
) -> None:
    """Batch-insert the accumulated rows in dependency order, then resolve print numbers."""
    cur.executemany(
        "INSERT INTO formats (name) VALUES (%s) ON CONFLICT DO NOTHING", [(f,) for f in formats]
    )
    cur.executemany(
        "INSERT INTO keywords (keyword) VALUES (%s) ON CONFLICT DO NOTHING",
        [(k,) for k in keywords],
    )
    cur.executemany(
        """
        INSERT INTO cards (
          card_id, slug, name, extended_title, name_normalized, rules_text,
          gold_cost, focus, force, chi, honor_requirement, personal_honor,
          province_strength, starting_honor, gold_production, back_card_id, is_back,
          is_unique, is_proxy, is_banned, errata_text, story, notes, extra
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (card_id) DO NOTHING
        """,
        list(cards.values()),
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
