import json
import re
import sys
from pathlib import Path

import psycopg2
from app.install.utils import normalize_empty
import logging


logger = logging.getLogger(__name__)


def generate_set_code(name: str, existing_codes: set[str]) -> str:
    """
    Generate a collision-free pseudo-L5R set code from the set name.

    Rules:
    - Derive initials from the words in the name.
    - Build a base code of 2–3 letters + any digits already in the name.
    - If the base collides with existing_codes, append 2, 3, ... until free.
    - Deterministic given the same existing_codes set state.
    """
    # Strip bracketed references like [1], [2]
    name_clean = re.sub(r"\[[^\]]*\]", "", name)

    # Split into words (letters/digits)
    words = re.findall(r"[A-Za-z0-9]+", name_clean)

    initials = ""

    for w in words:
        # If the word is purely digits, preserve them as a suffix
        if w.isdigit():
            initials += w
            continue

        # Take first letter for alpha words
        initials += w[0].upper()

    if not initials:
        # Fallback: grab first 3 letters from the whole name
        fallback = re.sub(r"[^A-Za-z]", "", name_clean).upper()
        initials = fallback or "SET"

    # Separate letters and digits so codes look like ABC, ABC2, etc.
    letters = "".join(ch for ch in initials if ch.isalpha())
    digits = "".join(ch for ch in initials if ch.isdigit())

    # Base: up to 3 letters + any in-name digits
    if letters:
        base = letters[:3].upper() + digits
    else:
        # If somehow we had only digits, prefix with S
        base = "S" + (digits or "1")

    code = base

    # Collision resolution
    if code in existing_codes:
        i = 2
        while True:
            candidate = f"{base}{i}"
            if candidate not in existing_codes:
                code = candidate
                break
            i += 1

    return code


def load_l5r_sets(json_path: Path, dsn: str):
    # Load scraped list from JSON
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON list")

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            # 1) Gather existing codes from the DB to avoid collisions
            cur.execute("SELECT code FROM l5r_sets WHERE code IS NOT NULL")
            rows = cur.fetchall()
            existing_codes: set[str] = {r[0] for r in rows if r[0]}

            # 2) Insert from JSON
            for i, row in enumerate(data, start=1):
                if len(row) < 2:
                    continue
                arc = row.get("Arc")
                set_name = row.get("Set")

                # Skip pure header rows that have only an arc
                if not set_name:
                    continue

                release_raw = normalize_empty(row.get("Release date"))
                featured_factions = normalize_empty(row.get("Featured Factions"))
                size_raw = normalize_empty(row.get("Size"))
                border = normalize_empty(row.get("Border"))
                notes = normalize_empty(row.get("Notes"))

                raw_code = normalize_empty(row.get("Code"))

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
                      release_raw,
                      featured_factions,
                      size_raw,
                      border,
                      code,
                      notes
                    )
                    VALUES (
                      %(arc)s,
                      %(set_name)s,
                      %(release_raw)s,
                      %(featured_factions)s,
                      %(size_raw)s,
                      %(border)s,
                      %(code)s,
                      %(notes)s
                    )
                    """,
                    {
                        "arc": arc,
                        "set_name": set_name,
                        "release_raw": release_raw,
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
        logger.error("Usage: python load_sets.py PATH_TO_l5r_sets.json 'dbname=l5r user=...'")
        sys.exit(1)

    json_file = Path(sys.argv[1])
    dsn = sys.argv[2]
    load_l5r_sets(json_file, dsn)
