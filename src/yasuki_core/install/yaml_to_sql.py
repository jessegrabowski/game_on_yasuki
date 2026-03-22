import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple

import psycopg2
import psycopg2.extras
import yaml

from yasuki_core.install.utils import (
    DECK_MAP,
    expected_card_image_path,
    normalize_name,
    strip_title,
)
import logging


logger = logging.getLogger(__name__)


def slugify_id(title: str, disambiguator: str = "") -> str:
    nfkd = unicodedata.normalize("NFKD", title)
    stripped = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    stripped = stripped.lower()
    stripped = re.sub(r"[^a-z0-9']+", "_", stripped)
    stripped = stripped.strip("_")
    base = stripped or "card"

    if disambiguator:
        dis_slug = re.sub(r"[^a-z0-9]+", "_", disambiguator.lower()).strip("_")
        return f"{base}_{dis_slug}"

    return base


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

    for kw in filtered_keywords:
        if kw.lower() == "inexperienced":
            return "inexp"

    for kw in filtered_keywords:
        if kw.startswith("Experienced") and " " not in kw.replace("Experienced", "", 1):
            remainder = kw[len("Experienced") :].strip()

            has_digit = any(c.isdigit() for c in remainder)
            has_alpha = any(c.isalpha() and c.upper() == c for c in remainder)

            if has_digit and has_alpha:
                match = re.match(r"(\d+)([A-Z]+)", remainder)
                if match:
                    level = match.group(1)
                    campaign = match.group(2).lower()
                    return f"exp{level}{campaign}"

            if remainder and not any(c.isdigit() for c in remainder):
                return f"exp_{remainder.lower()}"

    for kw in filtered_keywords:
        kw_lower = kw.lower()
        if kw_lower == "experienced 4" or kw_lower == "experienced4":
            return "exp4"
        if kw_lower == "experienced 3" or kw_lower == "experienced3":
            return "exp3"
        if kw_lower == "experienced 2" or kw_lower == "experienced2":
            return "exp2"
        if kw_lower == "experienced":
            return "exp"

    return None


def parse_legalities(value: list[str] | None) -> list[tuple[str, str]]:
    """
    Convert legality list into (format_name, status) pairs.
    Status is 'legal' or 'not_legal' (for 'Not Legal' / 'Proxy' entries).
    """
    result: list[tuple[str, str]] = []
    if not value:
        return result
    for fmt in value:
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
    t = record.get("type", "").lower()
    if "proxy" in t:
        return True
    for entry in record.get("legality") or []:
        lower = entry.lower()
        if "not legal" in lower and "proxy" in lower:
            return True
    return False


def map_deck(deck_str: str) -> str:
    try:
        return DECK_MAP[deck_str]
    except KeyError:
        raise ValueError(f"Unknown deck value: {deck_str!r}")


def map_card_type(type_str: str) -> str:
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


def upsert_card(cur, record: dict) -> str:
    title = record["title"]
    extended_title = record.get("extended_title", title)

    card_id = strip_title(extended_title)

    deck = map_deck(record.get("deck", DECK_FROM_TYPE[record["type"]]))
    ctype = map_card_type(record["type"])

    clan = record.get("clan")
    rules_text = record.get("text", "") or ""

    gold_cost = record.get("gold_cost")
    focus = record.get("focus")
    force = record.get("force")
    chi = record.get("chi")
    honor_req = record.get("honor_requirement")
    personal_honor = record.get("personal_honor")
    province_strength = record.get("province_strength")
    gold_production = record.get("gold_production")
    starting_honor = record.get("starting_honor")

    keyword_list = record.get("keywords", [])
    is_unique = detect_is_unique(keyword_list)
    is_proxy = detect_is_proxy(record)

    errata_text = record.get("errata_text")
    notes = record.get("card_notes")

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

    for fmt_name, status in parse_legalities(record.get("legality")):
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
    if number is None:
        return None, None, None

    raw = number.strip()
    if raw == "":
        return None, None, None

    m = re.match(r"^\s*([A-Za-z ]*?)\s*([0-9]+)\s*$", raw)
    if m:
        subset = m.group(1).strip() or None
        num_int = int(m.group(2))
        return subset, num_int, raw

    return None, None, raw


class NumberEntry(NamedTuple):
    subset: str | None
    number_int: int


def parse_all_numbers(raw: str | None) -> list[NumberEntry]:
    if not raw:
        return []

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    entries: list[NumberEntry] = []

    for part in parts:
        m = re.match(r"^\s*([A-Za-z ]*?)\s*([0-9]+)\s*$", part)
        if m:
            subset = m.group(1).strip() or None
            num_int = int(m.group(2))
            entries.append(NumberEntry(subset, num_int))
            continue

        m2 = re.match(r"^\s*([0-9]+)\s*$", part)
        if m2:
            num_int = int(m2.group(1))
            entries.append(NumberEntry(None, num_int))

    return entries


def choose_primary(entries: list[NumberEntry]) -> tuple[str | None, int | None]:
    if not entries:
        return None, None
    best = min(entries, key=lambda e: e.number_int)
    return best.subset, best.number_int


def upsert_print(
    cur,
    card_id: str,
    extended_title: str,
    set_name: str,
    record: dict,
    set_code_map: dict[str, str | None],
):
    rarity = record.get("rarity")
    flavor = record.get("flavor")
    artist = record.get("artist")
    notes = record.get("print_notes")

    number = record.get("number")
    collector_number = record.get("collector_number")
    collector_number_raw = (
        collector_number if collector_number else (str(number) if number is not None else None)
    )

    entries = parse_all_numbers(collector_number_raw)
    primary_subset, primary_int = choose_primary(entries)
    if not entries and number is not None:
        primary_int = number

    set_code = set_code_map.get(set_name)

    image_path = expected_card_image_path(extended_title, set_name) if set_name else None

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
            "collector_number_raw": collector_number_raw,
            "notes": notes,
            "image_path": image_path,
        },
    )

    (print_id,) = cur.fetchone()

    cur.execute("DELETE FROM print_numbers WHERE print_id = %s", (print_id,))
    for pos, entry in enumerate(entries):
        cur.execute(
            """
            INSERT INTO print_numbers (print_id, subset, number_int, position)
            VALUES (%s, %s, %s, %s)
            """,
            (print_id, entry.subset, entry.number_int, pos),
        )


def load_cards(cards_dir: Path, dsn: str):
    """
    Load card data from a directory of per-set YAML files.

    Parameters
    ----------
    cards_dir : Path
        Directory containing per-set YAML files (e.g. jade_edition.yaml)
    dsn : str
        PostgreSQL connection string
    """
    yaml_files = sorted(cards_dir.glob("*.yaml"))
    if not yaml_files:
        raise ValueError(f"No YAML files found in {cards_dir}")

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            set_code_map: dict[str, str | None] = {}
            try:
                cur.execute("SELECT set_name, code FROM l5r_sets")
                for set_name, code in cur.fetchall():
                    set_code_map[set_name] = code
            except psycopg2.errors.UndefinedTable:
                conn.rollback()
                set_code_map = {}

            total_cards = 0
            for yaml_file in yaml_files:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                set_name = data["set"]
                cards = data.get("cards", [])

                logger.info(f"Loading {yaml_file.name}: {len(cards)} cards")

                for record in cards:
                    title = record.get("title", "<unknown>")
                    extended_title = record.get("extended_title", title)
                    card_id = upsert_card(cur, record)
                    upsert_print(cur, card_id, extended_title, set_name, record, set_code_map)
                    total_cards += 1

            logger.info(
                f"Card import completed: {total_cards} card-prints from {len(yaml_files)} sets"
            )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        logger.error(
            "Usage: python yaml_to_sql.py PATH_TO_SETS_DIR 'postgres://user:pass@host:port/dbname'"
        )
        sys.exit(1)

    cards_dir = Path(sys.argv[1])
    dsn = sys.argv[2]
    load_cards(cards_dir, dsn)
