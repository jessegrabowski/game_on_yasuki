import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple

import psycopg2
import psycopg2.extras

from app.install.utils import (
    DECK_MAP,
    find_card_image,
    normalize_name,
    strip_title,
)
import logging


logger = logging.getLogger(__name__)


def slugify_id(title: str, disambiguator: str = "") -> str:
    """
    Simple, stable slug for card IDs when there's no explicit Id.
    Includes optional disambiguator for cards with same name but different stats.
    """
    nfkd = unicodedata.normalize("NFKD", title)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    # Keep letters, numbers, apostrophe as "a", everything else -> underscore
    stripped = stripped.lower()
    stripped = re.sub(r"[^a-z0-9']+", "_", stripped)
    stripped = stripped.strip("_")
    base = stripped or "card"

    if disambiguator:
        # Add disambiguator as suffix
        dis_slug = re.sub(r"[^a-z0-9]+", "_", disambiguator.lower()).strip("_")
        return f"{base}_{dis_slug}"

    return base


def parse_int_token(token: str | None) -> int | None:
    """
    Parse tokens like '3', '+1', '-2', '-', '', ' ' into int or None.
    '-' means 'no value' -> None.
    """
    if token is None:
        return None
    token = token.strip()
    if token == "" or token == "-":
        return None
    # Strip leading '+'
    if token.startswith("+"):
        token = token[1:]
    try:
        return int(token)
    except ValueError:
        return None


def parse_fc(value: str | None) -> tuple[int | None, int | None]:
    """
    F/C field like '1 2', '1 +1', '+0 +1'.
    """
    if not value:
        return None, None
    parts = value.split()
    if len(parts) < 2:
        parts += [""] * (2 - len(parts))
    force = parse_int_token(parts[0])
    chi = parse_int_token(parts[1])
    return force, chi


def parse_hr_cost_ph(value: str | None) -> tuple[int | None, int | None, int | None]:
    """
    HR/Cost/PH field like '- 7 1', '2 5 -', '1 0 -', '- 0 0'.
    """
    if not value:
        return None, None, None
    parts = value.split()
    if len(parts) < 3:
        parts += [""] * (3 - len(parts))
    hr = parse_int_token(parts[0])
    cost = parse_int_token(parts[1])
    ph = parse_int_token(parts[2])
    return hr, cost, ph


def parse_ps_gp_sh(value: str | None) -> tuple[int | None, int | None, int | None]:
    """
    PS/GP/SH field like '7 4 2', '+0 +0 -2', '10  '.
    If fewer than 3 tokens, missing ones become None.
    """
    if not value:
        return None, None, None
    parts = value.split()
    if len(parts) < 3:
        parts += [""] * (3 - len(parts))
    ps = parse_int_token(parts[0])
    gp = parse_int_token(parts[1])
    sh = parse_int_token(parts[2])
    return ps, gp, sh


def parse_keywords(value: str | None) -> list[str]:
    """
    Split 'Unique • Air • Shadowlands' into ['Unique', 'Air', 'Shadowlands'].
    """
    if not value:
        return []
    parts = [p.strip() for p in value.split("•")]
    return [p for p in parts if p]


def extract_experience_level(keywords: list[str]) -> str | None:
    """
    Extract experience level from keywords list.

    Returns
    -------
    exp_level : str or None
        Experience level identifier: 'exp', 'exp2', 'exp3', 'exp4', 'inexp', or special markers like 'exp2kyd'.
        Returns 'inexp' for explicitly inexperienced versions.
        Returns None for base (first printing) versions.
    """
    filtered_keywords = [kw for kw in keywords if not kw.startswith("Soul of")]

    # Check for "Inexperienced" keyword
    for kw in filtered_keywords:
        if kw.lower() == "inexperienced":
            return "inexp"

    # First, check for special experience markers (e.g., Experienced2KYD, ExperiencedCoM)
    # These must be checked before generic numbered levels to avoid false matches
    for kw in filtered_keywords:
        # Match patterns like "Experienced2KYD", "ExperiencedCoM", "Experienced 2KYD"
        # But ONLY if the keyword is JUST "Experienced..." (not part of a longer phrase)
        if kw.startswith("Experienced") and " " not in kw.replace("Experienced", "", 1):
            remainder = kw[len("Experienced") :].strip()  # Strip leading/trailing spaces

            # Check if it contains both digits and letters
            has_digit = any(c.isdigit() for c in remainder)
            has_alpha = any(c.isalpha() and c.upper() == c for c in remainder)

            if has_digit and has_alpha:
                # This is a campaign-specific marker like "2KYD" or "3KYD"
                # Extract level number and campaign code
                import re

                match = re.match(r"(\d+)([A-Z]+)", remainder)
                if match:
                    level = match.group(1)  # e.g., "2"
                    campaign = match.group(2).lower()  # e.g., "kyd"
                    return f"exp{level}{campaign}"  # No underscore for numbered+campaign

            # Check if it's just letters (no digits) like "ExperiencedCoM"
            if remainder and not any(c.isdigit() for c in remainder):
                # Format: "ExperiencedCoM" -> "exp_com"
                return f"exp_{remainder.lower()}"

    # Now check for standalone "Experienced" keywords with numbers
    # Only match if "Experienced X" is its own keyword, not part of a phrase
    for kw in filtered_keywords:
        kw_lower = kw.lower()
        # Match exact patterns: "Experienced 4", "Experienced4", etc.
        if kw_lower == "experienced 4" or kw_lower == "experienced4":
            return "exp4"
        if kw_lower == "experienced 3" or kw_lower == "experienced3":
            return "exp3"
        if kw_lower == "experienced 2" or kw_lower == "experienced2":
            return "exp2"
        # Match standalone "Experienced" only
        if kw_lower == "experienced":
            return "exp"

    # Base version (no experience or explicitly inexperienced)
    return None


def parse_legalities(value: str | None) -> list[tuple[str, str]]:
    """
    Parse Legality string into list of (format_name, status) pairs.
    Status is one of: 'legal', 'not_legal' (for 'Not Legal' formats), defaulting to 'legal'.
    """
    result: list[tuple[str, str]] = []
    if not value:
        return result
    for part in value.split("•"):
        fmt = part.strip()
        if not fmt:
            continue
        lower = fmt.lower()
        if "not legal" in lower or "proxy" in lower:
            status = "not_legal"
        else:
            status = "legal"
        result.append((fmt, status))
    return result


def detect_is_unique(keywords: list[str]) -> bool:
    return any(kw.lower() == "unique" for kw in keywords)


def detect_is_proxy(record: dict) -> bool:
    t = record.get("Type", "").lower()
    if "proxy" in t:
        return True
    leg = (record.get("Legality") or "").lower()
    if "not legal" in leg and "proxy" in leg:
        return True
    return False


def map_deck(deck_str: str) -> str:
    try:
        return DECK_MAP[deck_str]
    except KeyError:
        raise ValueError(f"Unknown deck value: {deck_str!r}")


def map_card_type(type_str: str) -> str:
    """
    For now assume the JSON Type values match the card_type enum values.
    (Strategy, Region, Event, Spell, Holding, Item, Personality, Follower,
     Wind, Celestial, Stronghold, Sensei, Ancestor, Ring, Proxy, Other,
     Clock, Territory)
    """
    return type_str


DECK_FROM_TYPE = {
    "Strategy": "Fate",
    "Region": "Dynasty",
    "Event": "Dynasty",
    "Spell": "Fate",
    "Holding": "Dynasty",
    "Item": "Fate",
    "Personality": "Dynasty",
    "Follower": "Fate",
    "Ancestor": "Fate",
    "Wind": "Pre-Game",
    "Sensei": "Pre-Game",
    "Celestial": "Dynasty",
    "Stronghold": "Pre-Game",
    "Ring": "Fate",
    "Proxy": "Other",
    "Other": "Other",
    "Clock": "Other",
    "Territory": "Other",
}


# -----------------------------
# DB insert helpers
# -----------------------------


def upsert_card(cur, record: dict) -> str:
    """
    Insert or update a card row and return the card_id.

    Uses Extended Title field (if present) to generate unique IDs that include experience markers.
    This eliminates collisions between different versions of the same personality.

    Examples:
    - "Bayushi Kachiko" -> bayushi_kachiko
    - "Bayushi Kachiko • Experienced" -> bayushi_kachiko_exp
    - "Bayushi Kachiko • Inexperienced" -> bayushi_kachiko_inexp
    """
    title = record["Title"]
    extended_title = record.get("Extended Title", title)

    # If explicit ID exists, use it
    explicit_id = record.get("Id")
    if explicit_id:
        card_id = explicit_id
    else:
        # Use Extended Title to generate ID (handles experience markers automatically)
        card_id = strip_title(extended_title)

    deck = map_deck(record.get("Deck", DECK_FROM_TYPE[record["Type"]]))
    ctype = map_card_type(record["Type"])

    clan = record.get("Clan")
    rules_text = record.get("Text", "") or ""

    # Stats
    cost_str = record.get("Cost")
    gold_cost = parse_int_token(cost_str) if cost_str is not None else None

    focus_str = record.get("Focus")
    focus = parse_int_token(focus_str) if focus_str is not None else None

    force = chi = None
    if "F/C" in record:
        force, chi = parse_fc(record.get("F/C"))

    honor_req = personal_honor = None
    if "HR/Cost/PH" in record:
        hr, cost2, ph = parse_hr_cost_ph(record.get("HR/Cost/PH"))
        # Prefer more specific cost if present
        if cost2 is not None:
            gold_cost = cost2
        honor_req = hr
        personal_honor = ph

    province_strength = starting_honor = None
    gold_production = None
    if "PS/GP/SH" in record:
        ps, gp, sh = parse_ps_gp_sh(record.get("PS/GP/SH"))
        province_strength = ps
        gold_production = gp
        starting_honor = sh

    # Keywords
    keyword_list = parse_keywords(record.get("Keywords"))
    is_unique = detect_is_unique(keyword_list)
    is_proxy = detect_is_proxy(record)

    errata_text = record.get("Erratum")
    notes = record.get("Notes")

    name_normalized = normalize_name(title)

    cur.execute(
        """
        INSERT INTO cards (
          id, name, name_normalized, extended_title,
          deck, type, clan,
          rules_text,
          gold_cost, focus,
          force, chi,
          honor_requirement, personal_honor,
          gold_production,
          province_strength, starting_honor,
          is_unique, is_proxy,
          errata_text, notes,
          extra
        ) VALUES (
          %(id)s, %(name)s, %(name_normalized)s, %(extended_title)s,
          %(deck)s, %(type)s, %(clan)s,
          %(rules_text)s,
          %(gold_cost)s, %(focus)s,
          %(force)s, %(chi)s,
          %(honor_requirement)s, %(personal_honor)s,
          %(gold_production)s,
          %(province_strength)s, %(starting_honor)s,
          %(is_unique)s, %(is_proxy)s,
          %(errata_text)s, %(notes)s,
          '{}'::jsonb
        )
        ON CONFLICT (id) DO UPDATE SET
          name = EXCLUDED.name,
          name_normalized = EXCLUDED.name_normalized,
          extended_title = EXCLUDED.extended_title,
          deck = EXCLUDED.deck,
          type = EXCLUDED.type,
          clan = EXCLUDED.clan,
          rules_text = EXCLUDED.rules_text,
          gold_cost = EXCLUDED.gold_cost,
          focus = EXCLUDED.focus,
          force = EXCLUDED.force,
          chi = EXCLUDED.chi,
          honor_requirement = EXCLUDED.honor_requirement,
          personal_honor = EXCLUDED.personal_honor,
          gold_production = EXCLUDED.gold_production,
          province_strength = EXCLUDED.province_strength,
          starting_honor = EXCLUDED.starting_honor,
          is_unique = EXCLUDED.is_unique,
          is_proxy = EXCLUDED.is_proxy,
          errata_text = EXCLUDED.errata_text,
          notes = EXCLUDED.notes
        """,
        {
            "id": card_id,
            "name": title,
            "name_normalized": name_normalized,
            "extended_title": extended_title,
            "deck": deck,
            "type": ctype,
            "clan": clan,
            "rules_text": rules_text,
            "gold_cost": gold_cost,
            "focus": focus,
            "force": force,
            "chi": chi,
            "honor_requirement": honor_req,
            "personal_honor": personal_honor,
            "gold_production": gold_production,
            "province_strength": province_strength,
            "starting_honor": starting_honor,
            "is_unique": is_unique,
            "is_proxy": is_proxy,
            "errata_text": errata_text,
            "notes": notes,
        },
    )

    # Keywords and card_keywords
    for kw in keyword_list:
        cur.execute(
            "INSERT INTO keywords (keyword) VALUES (%s) ON CONFLICT (keyword) DO NOTHING",
            (kw,),
        )
        cur.execute(
            """
            INSERT INTO card_keywords (card_id, keyword)
            VALUES (%s, %s)
            ON CONFLICT (card_id, keyword) DO NOTHING
            """,
            (card_id, kw),
        )

    # Legalities
    for fmt_name, status in parse_legalities(record.get("Legality")):
        cur.execute(
            "INSERT INTO formats (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (fmt_name,),
        )
        cur.execute(
            """
            INSERT INTO card_legalities (card_id, format_name, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (card_id, format_name) DO UPDATE SET
              status = EXCLUDED.status
            """,
            (card_id, fmt_name, status),
        )

    return card_id


def parse_collector_number(number: str | None) -> tuple[str | None, int | None, str | None]:
    """
    Parse things like:
      '109'          -> (None, 109, '109')
      'Lion 41'      -> ('Lion', 41, 'Lion 41')
      'Dragon 00'    -> ('Dragon', 0, 'Dragon 00')
    If no digits, subset = None, int = None, raw = original string.
    """
    if number is None:
        return None, None, None

    raw = number.strip()
    if raw == "":
        return None, None, None

    # Try prefix + digits
    m = re.match(r"^\s*([A-Za-z ]*?)\s*([0-9]+)\s*$", raw)
    if m:
        subset = m.group(1).strip() or None
        num_int = int(m.group(2))
        return subset, num_int, raw

    # Fallback: keep raw only
    return None, None, raw


class NumberEntry(NamedTuple):
    subset: str | None
    number_int: int


def parse_all_numbers(raw: str | None) -> list[NumberEntry]:
    """
    Parse a raw collector number string into a list of (subset, number_int).

    Examples:
      '109'                              -> [NumberEntry(None, 109)]
      'Lion 09'                          -> [NumberEntry('Lion', 9)]
      'Unicorn 07,Unicorn 20'            -> [NumberEntry('Unicorn', 7), NumberEntry('Unicorn', 20)]
      'Lion 10,Lion 17,Shadowlands 20'   -> [...]
    """
    if not raw:
        return []

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    entries: list[NumberEntry] = []

    for part in parts:
        # Try: optional subset + number
        m = re.match(r"^\s*([A-Za-z ]*?)\s*([0-9]+)\s*$", part)
        if m:
            subset = m.group(1).strip() or None
            num_int = int(m.group(2))
            entries.append(NumberEntry(subset, num_int))
            continue

        # Fallback: pure digits?
        m2 = re.match(r"^\s*([0-9]+)\s*$", part)
        if m2:
            num_int = int(m2.group(1))
            entries.append(NumberEntry(None, num_int))
            continue

        # If we get here, we couldn't parse this fragment → skip it, or log
        # For now we skip; you could also append (None, None) etc.
        # print(f"Warning: could not parse collector number fragment: {part!r}")

    return entries


def choose_primary(entries: list[NumberEntry]) -> tuple[str | None, int | None]:
    if not entries:
        return None, None

    # Simple rule: choose the one with the smallest number_int
    best = min(entries, key=lambda e: e.number_int)
    return best.subset, best.number_int


def upsert_prints(
    cur,
    card_id: str,
    extended_title: str,
    version_list: list[dict],
    set_code_map: dict[str, str | None],
):
    for info in version_list:
        set_name = info.get("Set")
        rarity = info.get("Rarity")
        flavor = info.get("Flavor")
        artist = info.get("Artist")
        number_raw = info.get("Number")
        notes = info.get("Notes")

        # Parse all numbers
        entries = parse_all_numbers(number_raw)
        primary_subset, primary_int = choose_primary(entries)

        set_code = set_code_map.get(set_name)

        # Find image path using Extended Title
        image_path = find_card_image(extended_title, set_name) if set_name else None

        # 1) Insert into prints
        cur.execute(
            """
            INSERT INTO prints (
              card_id,
              set_name,
              set_code,
              rarity,
              flavor_text,
              artist,
              primary_subset,
              primary_number_int,
              collector_number_raw,
              notes,
              image_path,
              release_date,
              extra
            ) VALUES (
              %(card_id)s,
              %(set_name)s,
              %(set_code)s,
              %(rarity)s,
              %(flavor_text)s,
              %(artist)s,
              %(primary_subset)s,
              %(primary_number_int)s,
              %(collector_number_raw)s,
              %(notes)s,
              %(image_path)s,
              NULL,
              '{}'::jsonb
            )
            ON CONFLICT (card_id, set_name, collector_number_raw) DO UPDATE SET
              rarity = EXCLUDED.rarity,
              flavor_text = EXCLUDED.flavor_text,
              artist = EXCLUDED.artist,
              primary_subset = EXCLUDED.primary_subset,
              primary_number_int = EXCLUDED.primary_number_int,
              notes = EXCLUDED.notes,
              image_path = EXCLUDED.image_path
            RETURNING print_id
            """,
            {
                "card_id": card_id,
                "set_name": set_name,
                "set_code": set_code,
                "rarity": rarity,
                "flavor_text": flavor,
                "artist": artist,
                "primary_subset": primary_subset,
                "primary_number_int": primary_int,
                "collector_number_raw": number_raw,
                "notes": notes,
                "image_path": image_path,
            },
        )

        (print_id,) = cur.fetchone()

        # 2) Insert all number entries into print_numbers
        #    (delete old ones in case this is an update)
        cur.execute("DELETE FROM print_numbers WHERE print_id = %s", (print_id,))
        for pos, entry in enumerate(entries):
            cur.execute(
                """
                INSERT INTO print_numbers (print_id, subset, number_int, position)
                VALUES (%s, %s, %s, %s)
                """,
                (print_id, entry.subset, entry.number_int, pos),
            )


# -----------------------------
# Main import routine
# -----------------------------


def load_cards(json_path: Path, dsn: str):
    """
    json_path: JSON file containing a list of card records.
    dsn: psycopg DSN, e.g. "dbname=l5r user=postgres password=secret host=localhost"
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON list of card records")

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Build set_name -> code map from l5r_sets (if present)
            set_code_map: dict[str, str | None] = {}
            try:
                cur.execute("SELECT set_name, code FROM l5r_sets")
                for set_name, code in cur.fetchall():
                    set_code_map[set_name] = code
            except psycopg2.errors.UndefinedTable:
                # If l5r_sets doesn't exist yet, just leave map empty
                conn.rollback()
                set_code_map = {}

            for i, rec in enumerate(data, start=1):
                title = rec.get("Title", "<unknown>")
                extended_title = rec.get("Extended Title", title)
                logger.info(f"[{i}/{len(data)}] Importing {title!r}")
                card_id = upsert_card(cur, rec)

                version = rec.get("Versions") or []
                if isinstance(version, list):
                    upsert_prints(cur, card_id, extended_title, version, set_code_map)

        logger.info("Card import completed successfully")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        logger.error(
            "Usage: python load_cards.py PATH_TO_CARDS.json 'postgres://user:pass@host:port/dbname'"
        )
        logger.error(
            "   or: python load_cards.py PATH_TO_CARDS.json 'dbname=l5r user=postgres password=secret host=localhost'"
        )
        sys.exit(1)

    json_file = Path(sys.argv[1])
    dsn = sys.argv[2]
    load_cards(json_file, dsn)
