import datetime
import logging
import re
import sys
from pathlib import Path

import psycopg
import yaml

logger = logging.getLogger(__name__)


_ORDINAL = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)


def coerce_date(raw) -> datetime.date | None:
    """
    Parse a date, returning None for missing or unparseable values.

    Accepts ISO ``YYYY-MM-DD`` and long form like ``November 5th, 2012`` (ordinal suffix tolerated).
    """
    if raw is None:
        return None
    if isinstance(raw, datetime.date):
        return raw
    text = str(raw).strip()
    if not text or text == "-":
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(_ORDINAL.sub(r"\1", text), "%B %d, %Y").date()
    except ValueError:
        logger.warning("Unparseable date, storing NULL: %r", raw)
        return None


def coerce_int(raw) -> int | None:
    """Parse an integer, returning None when the value is missing or non-numeric."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def set_slug(name: str) -> str:
    """Filesystem/URL slug for a set name (lowercase alphanumerics joined by underscores)."""
    s = name.lower().replace("&", "and").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def load_l5r_sets(set_info_path: Path, dsn: str) -> None:
    """
    Load set metadata from the arc-grouped set_info YAML into l5r_sets.

    One row per set name; a name that recurs across arcs (e.g. promotional cards) is kept once.

    Parameters
    ----------
    set_info_path : path
        Path to the arc-grouped set_info YAML.
    dsn : str
        PostgreSQL connection string.
    """
    data = yaml.safe_load(set_info_path.read_text(encoding="utf-8"))
    rows: dict[str, tuple] = {}
    for arc in data["arcs"]:
        for entry in arc.get("sets") or []:
            name = entry["set_name"].strip()
            rows.setdefault(
                name,
                (
                    name,
                    set_slug(name),
                    entry.get("code"),
                    arc["name"],
                    coerce_date(entry.get("release_date")),
                    bool(entry.get("digital", False)),
                    entry.get("featured_factions"),
                    coerce_int(entry.get("size")),
                    entry.get("border"),
                    entry.get("notes"),
                ),
            )

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Self-migrate so the loader populates the column on databases created before it was added.
        cur.execute("ALTER TABLE l5r_sets ADD COLUMN IF NOT EXISTS code TEXT")
        cur.executemany(
            """
            INSERT INTO l5r_sets
              (set_name, set_slug, code, arc, release_date, digital, featured_factions,
               size_raw, border, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (set_name) DO UPDATE SET
              set_slug = EXCLUDED.set_slug, code = EXCLUDED.code, arc = EXCLUDED.arc,
              release_date = EXCLUDED.release_date, digital = EXCLUDED.digital,
              featured_factions = EXCLUDED.featured_factions, size_raw = EXCLUDED.size_raw,
              border = EXCLUDED.border, notes = EXCLUDED.notes
            """,
            list(rows.values()),
        )
        conn.commit()
    logger.info("Loaded %d sets", len(rows))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_l5r_sets(Path(sys.argv[1]), sys.argv[2])
