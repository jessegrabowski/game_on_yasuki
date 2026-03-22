import datetime
import re
import sys
from pathlib import Path

import psycopg2
import yaml

from yasuki_core.install.utils import normalize_empty
import logging


logger = logging.getLogger(__name__)


def _coerce_release_date(raw) -> datetime.date | None:
    if raw is None:
        return None
    if isinstance(raw, datetime.date):
        return raw
    s = str(raw).strip()
    if not s or s == "-":
        return None
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        logger.warning("Unparseable release_date, storing as NULL: %r", raw)
        return None


def generate_set_code(name: str, existing_codes: set[str]) -> str:
    """
    Generate a collision-free pseudo-L5R set code from the set name.

    Rules:
    - Derive initials from the words in the name.
    - Build a base code of 2–3 letters + any digits already in the name.
    - If the base collides with existing_codes, append 2, 3, ... until free.
    - Deterministic given the same existing_codes set state.
    """
    name_clean = re.sub(r"\[[^\]]*\]", "", name)

    words = re.findall(r"[A-Za-z0-9]+", name_clean)

    initials = ""

    for w in words:
        if w.isdigit():
            initials += w
            continue
        initials += w[0].upper()

    if not initials:
        fallback = re.sub(r"[^A-Za-z]", "", name_clean).upper()
        initials = fallback or "SET"

    letters = "".join(ch for ch in initials if ch.isalpha())
    digits = "".join(ch for ch in initials if ch.isdigit())

    if letters:
        base = letters[:3].upper() + digits
    else:
        base = "S" + (digits or "1")

    code = base

    if code in existing_codes:
        i = 2
        while True:
            candidate = f"{base}{i}"
            if candidate not in existing_codes:
                code = candidate
                break
            i += 1

    return code


def load_l5r_sets(yaml_path: Path, dsn: str):
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    arcs = data.get("arcs")
    if not arcs:
        raise ValueError("Expected 'arcs' key in set info YAML")

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT code FROM l5r_sets WHERE code IS NOT NULL")
            rows = cur.fetchall()
            existing_codes: set[str] = {r[0] for r in rows if r[0]}

            i = 0
            for arc_group in arcs:
                arc = arc_group["name"]
                for row in arc_group["sets"]:
                    i += 1
                    set_name = row["set_name"]

                    release_date = _coerce_release_date(row.get("release_date"))
                    digital = bool(row.get("digital", False))
                    featured_factions = normalize_empty(row.get("featured_factions"))
                    size_raw = row.get("size")
                    if size_raw is not None:
                        size_raw = str(size_raw)
                    border = normalize_empty(row.get("border"))
                    notes = normalize_empty(row.get("notes"))

                    raw_code = normalize_empty(row.get("code"))

                    if raw_code:
                        code = raw_code
                        existing_codes.add(code)
                    else:
                        code = generate_set_code(set_name, existing_codes)
                        existing_codes.add(code)

                    logger.info(f"[{i}] {arc!r} – {set_name!r} → code={code!r}")

                    cur.execute(
                        """
                        INSERT INTO l5r_sets (
                          arc,
                          set_name,
                          release_date,
                          digital,
                          featured_factions,
                          size_raw,
                          border,
                          code,
                          notes
                        )
                        VALUES (
                          %(arc)s,
                          %(set_name)s,
                          %(release_date)s,
                          %(digital)s,
                          %(featured_factions)s,
                          %(size_raw)s,
                          %(border)s,
                          %(code)s,
                          %(notes)s
                        )
                        ON CONFLICT (arc, set_name) DO UPDATE SET
                          release_date = EXCLUDED.release_date,
                          digital = EXCLUDED.digital,
                          featured_factions = EXCLUDED.featured_factions,
                          size_raw = EXCLUDED.size_raw,
                          border = EXCLUDED.border,
                          code = EXCLUDED.code,
                          notes = EXCLUDED.notes
                        """,
                        {
                            "arc": arc,
                            "set_name": set_name,
                            "release_date": release_date,
                            "digital": digital,
                            "featured_factions": featured_factions,
                            "size_raw": size_raw,
                            "border": border,
                            "code": code,
                            "notes": notes,
                        },
                    )

        logger.info("Set import completed")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        logger.error("Usage: python sets_to_sql.py PATH_TO_set_info.yaml 'dbname=l5r user=...'")
        sys.exit(1)

    yaml_file = Path(sys.argv[1])
    dsn = sys.argv[2]
    load_l5r_sets(yaml_file, dsn)
