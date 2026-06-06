import os
import re
from contextlib import contextmanager
from collections.abc import Generator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import logging

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None

_PRIVATE_HOST_RE = re.compile(
    r"^("
    r"localhost|"
    r"127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"[a-zA-Z][a-zA-Z0-9_-]*"  # bare hostnames (e.g. Docker service names like 'db')
    r")$"
)


def _extract_host(dsn: str) -> str:
    """Extract the hostname from a PostgreSQL DSN."""
    after_scheme = dsn.split("://", 1)[-1]
    authority = after_scheme.split("/", 1)[0].split("?", 1)[0]
    host_port = authority.rsplit("@", 1)[-1]
    host = host_port.split(":")[0]
    return host


def _is_private_dsn(dsn: str) -> bool:
    """
    Detect whether a DSN points at a private or local host.

    Returns True for localhost, loopback, RFC-1918 addresses, and bare
    hostnames (single-label, no dots) such as Docker Compose service names.
    """
    return bool(_PRIVATE_HOST_RE.match(_extract_host(dsn)))


def mask_dsn(dsn: str) -> str:
    """Replace the password portion of a DSN with ``****`` for safe logging."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1****\2", dsn)


def _escape_like(value: str) -> str:
    """Escape ``%`` and ``_`` wildcards for use in ILIKE patterns."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_connection_string() -> str:
    """
    Get PostgreSQL connection string from environment or use default.

    Checks YASUKI_DATABASE_URL first, then DATABASE_URL (used by Railway and
    other PaaS providers), then falls back to localhost.

    Appends ``sslmode=require`` automatically for non-private hosts
    (i.e. public cloud databases) when no sslmode is already set.

    Returns
    -------
    dsn : str
        PostgreSQL connection string
    """
    dsn = os.environ.get(
        "YASUKI_DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://localhost/yasuki")
    )
    if "sslmode" not in dsn and not _is_private_dsn(dsn):
        separator = "&" if "?" in dsn else "?"
        dsn += f"{separator}sslmode=require"
    return dsn


def init_pool(min_size: int = 2, max_size: int = 20) -> None:
    """
    Initialize the module-level connection pool.

    Safe to call multiple times; subsequent calls are no-ops if the pool
    is already open.

    Parameters
    ----------
    min_size : int
        Minimum number of idle connections kept in the pool
    max_size : int
        Maximum number of connections the pool will open
    """
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(
        conninfo=get_connection_string(),
        min_size=min_size,
        max_size=max_size,
        open=True,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "options": "-c statement_timeout=15000",
            "connect_timeout": 5,
        },
    )
    logger.info("Database connection pool initialized (min=%d, max=%d)", min_size, max_size)


def close_pool() -> None:
    """Close the connection pool and release all connections."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


@contextmanager
def get_db_connection() -> Generator[psycopg.Connection, None, None]:
    """
    Context manager for database connections from the pool.

    Initializes the pool on first use if it has not been opened yet.

    Yields
    ------
    conn : psycopg.Connection
        Database connection with autocommit enabled and dict_row factory
    """
    if _pool is None:
        init_pool()
    with _pool.connection() as conn:
        yield conn


# Shared card SELECT: card-level columns, multi-valued clan/type/deck as text arrays, and the front
# image path from the card's first printing (NULL until print images are materialized).
_CARD_SELECT = """
    SELECT
        c.card_id,
        c.name,
        c.extended_title,
        (SELECT array_agg(deck::text ORDER BY deck) FROM card_decks d WHERE d.card_id = c.card_id)
            AS decks,
        (SELECT array_agg(type::text ORDER BY type) FROM card_card_types t WHERE t.card_id = c.card_id)
            AS types,
        (SELECT array_agg(clan ORDER BY clan) FROM card_clans cl WHERE cl.card_id = c.card_id)
            AS clans,
        (SELECT array_agg(keyword ORDER BY keyword) FROM card_keywords k WHERE k.card_id = c.card_id)
            AS keywords,
        c.rules_text AS text,
        c.gold_cost, c.focus, c.force, c.chi,
        c.honor_requirement, c.personal_honor, c.gold_production,
        c.province_strength, c.starting_honor,
        c.is_unique, c.is_proxy, c.is_banned, c.extra,
        img.image_path
    FROM cards c
    LEFT JOIN LATERAL (
        SELECT pi.path AS image_path
        FROM prints p
        JOIN print_images pi ON pi.print_id = p.print_id AND pi.role = 'front'
        WHERE p.card_id = c.card_id
        ORDER BY p.print_id, pi.image_index
        LIMIT 1
    ) img ON true"""


def query_all_cards() -> list[dict]:
    """Fetch every card with its multi-valued attributes and front image, ordered by name."""
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(f"{_CARD_SELECT} ORDER BY c.name")
        return cur.fetchall()


def search_cards(query: str = "", deck_filter: str | None = None) -> list[dict]:
    """
    Search for cards by name or text.

    Parameters
    ----------
    query : str
        Search query (searches name and rules text)
    deck_filter : str, optional
        Filter by deck type ('FATE' or 'DYNASTY')

    Returns
    -------
    cards : list of dict
        Matching card records
    """
    conditions = []
    params = []

    if query:
        conditions.append("(c.name ILIKE %s ESCAPE '\\' OR c.rules_text ILIKE %s ESCAPE '\\')")
        search_pattern = f"%{_escape_like(query)}%"
        params.extend([search_pattern, search_pattern])

    if deck_filter:
        conditions.append(
            "EXISTS (SELECT 1 FROM card_decks d WHERE d.card_id = c.card_id AND d.deck = %s::deck_type)"
        )
        params.append(deck_filter)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_CARD_SELECT} {where_clause} ORDER BY c.name", params)
            return cur.fetchall()


def query_all_prints() -> list[dict]:
    """
    Fetch all card prints from database with their set information.

    Returns
    -------
    prints : list of dict
        List of print records with card data and set information.
        Each print represents a unique card+set combination.
    """
    logger.debug("Querying all prints from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.card_id,
                    c.name,
                    c.extended_title,
                    (SELECT array_agg(deck::text ORDER BY deck) FROM card_decks d
                       WHERE d.card_id = c.card_id) AS decks,
                    (SELECT array_agg(type::text ORDER BY type) FROM card_card_types t
                       WHERE t.card_id = c.card_id) AS types,
                    (SELECT array_agg(clan ORDER BY clan) FROM card_clans cl
                       WHERE cl.card_id = c.card_id) AS clans,
                    c.rules_text AS text,
                    c.gold_cost, c.focus, c.force, c.chi,
                    c.honor_requirement, c.personal_honor, c.gold_production,
                    c.province_strength, c.starting_honor, c.is_unique,
                    p.print_id,
                    s.set_name,
                    p.rarity,
                    p.artist,
                    pi.path AS image_path,
                    p.flavor_text
                FROM prints p
                JOIN cards c ON c.card_id = p.card_id
                JOIN l5r_sets s ON s.set_id = p.set_id
                LEFT JOIN print_images pi
                    ON pi.print_id = p.print_id AND pi.role = 'front' AND pi.size = 'master'
                ORDER BY c.name, s.set_name
            """)
            results = cur.fetchall()
            logger.debug(f"Retrieved {len(results)} prints from database")
            return results


def get_card_by_id(card_id: str) -> dict | None:
    """
    Fetch a single card by ID.

    Parameters
    ----------
    card_id : str
        Card ID

    Returns
    -------
    card : dict or None
        Card record or None if not found
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{_CARD_SELECT} WHERE c.card_id = %s", (card_id,))
            return cur.fetchone()


def get_prints_by_card_id(card_id: str) -> list[dict]:
    """
    Fetch all prints for a specific card.

    Parameters
    ----------
    card_id : str
        Card ID

    Returns
    -------
    prints : list of dict
        All prints of this card with set and image information
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.print_id, p.card_id, s.set_name, p.rarity, p.artist,
                    front.path AS image_path, back.path AS back_image_path, p.flavor_text
                FROM prints p
                JOIN l5r_sets s ON s.set_id = p.set_id
                LEFT JOIN print_images front
                    ON front.print_id = p.print_id AND front.role = 'front' AND front.size = 'master'
                LEFT JOIN print_images back
                    ON back.print_id = p.print_id AND back.role = 'back' AND back.size = 'master'
                WHERE p.card_id = %s
                ORDER BY s.set_name
            """,
                (card_id,),
            )
            return cur.fetchall()


def get_cards_by_names(names: list[str]) -> list[dict]:
    """
    Fetch cards matching a list of names, including their prints.

    Matches against both ``name`` and ``extended_title`` (case-insensitive).
    Used for deck import to resolve human-readable names to card records.

    Parameters
    ----------
    names : list of str
        Card names to look up

    Returns
    -------
    cards : list of dict
        Matched card records, each with a ``prints`` key containing
        a list of print dicts (print_id, set_name, image_path, flavor_text)
    """
    if not names:
        return []
    lower_names = [n.lower() for n in names]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"{_CARD_SELECT} "
                "WHERE lower(c.name) = ANY(%s) OR lower(c.extended_title) = ANY(%s) "
                "ORDER BY c.name",
                (lower_names, lower_names),
            )
            cards = cur.fetchall()

            if not cards:
                return []

            card_ids = [c["card_id"] for c in cards]
            cur.execute(
                """
                SELECT p.print_id, p.card_id, s.set_name, pi.path AS image_path,
                    back.path AS back_image_path, p.flavor_text
                FROM prints p
                JOIN l5r_sets s ON s.set_id = p.set_id
                LEFT JOIN print_images pi
                    ON pi.print_id = p.print_id AND pi.role = 'front' AND pi.size = 'master'
                LEFT JOIN print_images back
                    ON back.print_id = p.print_id AND back.role = 'back' AND back.size = 'master'
                WHERE p.card_id = ANY(%s)
                ORDER BY p.print_id
                """,
                (card_ids,),
            )
            prints_by_card: dict[str, list] = {}
            for row in cur.fetchall():
                prints_by_card.setdefault(row["card_id"], []).append(row)

            for card in cards:
                card["prints"] = prints_by_card.get(card["card_id"], [])

            return cards


def query_all_formats() -> list[str]:
    """
    Fetch all format names from database.

    Returns
    -------
    formats : list of str
        List of format names
    """
    logger.debug("Querying all formats from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM formats ORDER BY name")
            results = [row["name"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} formats from database")
            return results


def query_cards_by_legality(format_name: str) -> list[str]:
    """
    Fetch the ids of cards legal in a format.

    Parameters
    ----------
    format_name : str
        Format name to filter by.

    Returns
    -------
    card_ids : list of str
        Ids of cards legal in the format.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT card_id FROM card_legalities WHERE format_name = %s ORDER BY card_id",
                (format_name,),
            )
            return [row["card_id"] for row in cur.fetchall()]


def query_all_sets() -> list[str]:
    """
    Fetch all unique set names from the prints table.

    Returns
    -------
    sets : list of str
        List of unique set names, sorted alphabetically
    """
    logger.debug("Querying all sets from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT s.set_name
                FROM l5r_sets s
                JOIN prints p ON p.set_id = s.set_id
                ORDER BY s.set_name
            """)
            results = [row["set_name"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} sets from database")
            return results


def query_all_decks() -> list[str]:
    """
    Fetch all unique deck types from cards.

    Returns
    -------
    decks : list of str
        List of deck types (e.g., FATE, DYNASTY)
    """
    logger.debug("Querying all deck types from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT deck::text AS deck FROM card_decks ORDER BY deck")
            results = [row["deck"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} deck types from database")
            return results


def get_card_backs() -> dict[tuple[str, str], str]:
    """
    Fetch the generic card backs.

    Returns
    -------
    backs : dict mapping (deck, era) to str
        Image path for each ``(deck, era)`` back, where era is one of ``'old'``, ``'new'``,
        ``'token'``.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT deck::text AS deck, era, image_path FROM card_backs")
            return {(row["deck"], row["era"]): row["image_path"] for row in cur.fetchall()}


def query_all_clans() -> list[str]:
    """
    Fetch all unique clans.

    Returns
    -------
    clans : list of str
        Clan names, sorted alphabetically.
    """
    logger.debug("Querying all clans from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT clan FROM card_clans ORDER BY clan")
            results = [row["clan"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} clans from database")
            return results


def query_all_types() -> list[str]:
    """
    Fetch all unique card types from cards.

    Returns
    -------
    types : list of str
        List of card types (e.g., Personality, Holding, Event)
    """
    logger.debug("Querying all card types from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT type::text AS type FROM card_card_types ORDER BY type")
            results = [row["type"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} card types from database")
            return results


def query_all_rarities() -> list[str]:
    """
    Fetch all unique rarities from prints.

    Returns
    -------
    rarities : list of str
        List of rarity values, sorted alphabetically
    """
    logger.debug("Querying all rarities from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT rarity
                FROM prints
                WHERE rarity IS NOT NULL AND rarity != ''
                ORDER BY rarity
            """)
            results = [row["rarity"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} rarities from database")
            return results


def query_types_by_deck(deck_types: list[str]) -> list[str]:
    """
    Fetch card types filtered by deck type(s).

    Parameters
    ----------
    deck_types : list of str
        List of deck types to filter by (e.g., ['FATE', 'DYNASTY'])

    Returns
    -------
    types : list of str
        List of card types for the specified deck(s), sorted alphabetically
    """
    logger.debug(f"Querying card types for decks: {deck_types}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT t.type::text AS type
                FROM card_card_types t
                WHERE EXISTS (
                    SELECT 1 FROM card_decks d
                    WHERE d.card_id = t.card_id AND d.deck = ANY(%s::deck_type[])
                )
                ORDER BY type
            """,
                (deck_types,),
            )
            results = [row["type"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} card types for decks {deck_types}")
            return results


def query_stat_ranges() -> dict[str, tuple[int, int]]:
    """
    Fetch min and max values for all numeric card statistics.

    Returns
    -------
    ranges : dict of str to tuple of int
        Dictionary mapping stat field name to (min, max) tuple
    """
    logger.debug("Querying statistic ranges from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    MIN(force) as force_min, MAX(force) as force_max,
                    MIN(chi) as chi_min, MAX(chi) as chi_max,
                    MIN(honor_requirement) as honor_req_min, MAX(honor_requirement) as honor_req_max,
                    MIN(gold_cost) as gold_cost_min, MAX(gold_cost) as gold_cost_max,
                    MIN(personal_honor) as personal_honor_min, MAX(personal_honor) as personal_honor_max,
                    MIN(province_strength) as province_str_min, MAX(province_strength) as province_str_max,
                    MIN(gold_production) as gold_prod_min, MAX(gold_production) as gold_prod_max,
                    MIN(starting_honor) as starting_honor_min, MAX(starting_honor) as starting_honor_max,
                    MIN(focus) as focus_min, MAX(focus) as focus_max
                FROM cards
            """)
            row = cur.fetchone()

            ranges = {
                "force": (row["force_min"] or 0, row["force_max"] or 20),
                "chi": (row["chi_min"] or -2, row["chi_max"] or 15),
                "honor_requirement": (row["honor_req_min"] or 0, row["honor_req_max"] or 40),
                "gold_cost": (row["gold_cost_min"] or 0, row["gold_cost_max"] or 20),
                "personal_honor": (row["personal_honor_min"] or 0, row["personal_honor_max"] or 6),
                "province_strength": (row["province_str_min"] or -1, row["province_str_max"] or 20),
                "gold_production": (row["gold_prod_min"] or -1, row["gold_prod_max"] or 8),
                "starting_honor": (
                    row["starting_honor_min"] or -20,
                    row["starting_honor_max"] or 15,
                ),
                "focus": (row["focus_min"] or 0, row["focus_max"] or 5),
            }

            logger.debug(f"Retrieved statistic ranges: {ranges}")
            return ranges


def query_types_with_stat(stat_name: str) -> tuple[list[str], list[str]]:
    """
    Find which card types and deck types have a specific statistic.

    Parameters
    ----------
    stat_name : str
        Database column name (e.g., 'force', 'gold_production', 'starting_honor')

    Returns
    -------
    types : list of str
        Card types that can have this statistic
    decks : list of str
        Deck types that can have this statistic
    """
    # Whitelist of valid stat column names to prevent SQL injection
    valid_stats = {
        "force",
        "chi",
        "honor_requirement",
        "gold_cost",
        "personal_honor",
        "province_strength",
        "gold_production",
        "starting_honor",
        "focus",
    }

    if stat_name not in valid_stats:
        raise ValueError(f"Invalid stat name: {stat_name}")

    logger.debug(f"Querying types with stat '{stat_name}'")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT DISTINCT t.type::text AS type
                FROM card_card_types t JOIN cards c ON c.card_id = t.card_id
                WHERE c.{stat_name} IS NOT NULL
                ORDER BY type
            """)
            types = [row["type"] for row in cur.fetchall()]

            cur.execute(f"""
                SELECT DISTINCT d.deck::text AS deck
                FROM card_decks d JOIN cards c ON c.card_id = d.card_id
                WHERE c.{stat_name} IS NOT NULL
                ORDER BY deck
            """)
            decks = [row["deck"] for row in cur.fetchall()]

            logger.debug(f"Stat '{stat_name}' found in types: {types}, decks: {decks}")
            return types, decks


def query_all_stat_type_mappings() -> dict[str, tuple[set[str], set[str]]]:
    """
    Query all stat-to-type/deck mappings in a single database call.

    Returns
    -------
    mappings : dict of str to tuple of set
        Maps stat name to (set of types, set of decks) that can have that stat
    """
    valid_stats = [
        "force",
        "chi",
        "honor_requirement",
        "gold_cost",
        "personal_honor",
        "province_strength",
        "gold_production",
        "starting_honor",
        "focus",
    ]

    logger.debug("Querying all stat-type mappings")
    mappings = {}

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            for stat in valid_stats:
                # Single query per stat, but all done in one connection
                cur.execute(f"""
                    SELECT
                        (SELECT array_agg(DISTINCT t.type::text ORDER BY t.type::text)
                           FROM card_card_types t JOIN cards c ON c.card_id = t.card_id
                           WHERE c.{stat} IS NOT NULL) AS types,
                        (SELECT array_agg(DISTINCT d.deck::text ORDER BY d.deck::text)
                           FROM card_decks d JOIN cards c ON c.card_id = d.card_id
                           WHERE c.{stat} IS NOT NULL) AS decks
                """)
                row = cur.fetchone()
                types = set(row["types"]) if row["types"] else set()
                decks = set(row["decks"]) if row["decks"] else set()
                mappings[stat] = (types, decks)

    logger.debug(f"Retrieved mappings for {len(mappings)} stats")
    return mappings


def query_sets_by_format(format_name: str) -> list[str]:
    """
    Fetch the set names that belong to a format's arc/era.

    Arc-specific formats (e.g. "Clan Wars (Imperial)") return only sets from that arc; cross-era
    formats (Modern, Legacy) return every set holding a card legal in the format.

    Parameters
    ----------
    format_name : str
        Format name to filter by.

    Returns
    -------
    sets : list of str
        Set names, sorted alphabetically.
    """
    logger.debug("Querying sets for format '%s'", format_name)

    cross_era_formats = {"Modern", "Legacy", "Not Legal (Proxy)", "Unreleased"}
    legal = "p.card_id IN (SELECT card_id FROM card_legalities WHERE format_name = %s)"
    arc_match = (
        "(s.arc ILIKE '%%' || SPLIT_PART(%s, ' (', 1) || '%%'"
        " OR %s ILIKE '%%' || s.arc || '%%'"
        " OR s.arc = SPLIT_PART(%s, ' (', 1))"
    )
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if format_name in cross_era_formats:
                cur.execute(
                    f"SELECT DISTINCT s.set_name FROM l5r_sets s JOIN prints p ON p.set_id = s.set_id"
                    f" WHERE {legal} ORDER BY s.set_name",
                    (format_name,),
                )
            else:
                cur.execute(
                    f"SELECT DISTINCT s.set_name FROM l5r_sets s JOIN prints p ON p.set_id = s.set_id"
                    f" WHERE {legal} AND {arc_match} ORDER BY s.set_name",
                    (format_name, format_name, format_name, format_name),
                )
            return [row["set_name"] for row in cur.fetchall()]


_ALLOWED_COLUMNS = {
    "is_unique",
    "is_proxy",
    "is_banned",
    "name",
    "force",
    "chi",
    "honor_requirement",
    "gold_cost",
    "personal_honor",
    "province_strength",
    "gold_production",
    "starting_honor",
    "focus",
}

_NUMERIC_STATS = (
    "force",
    "chi",
    "honor_requirement",
    "gold_cost",
    "personal_honor",
    "province_strength",
    "gold_production",
    "starting_honor",
    "focus",
)


def _build_card_filter(
    text_query: str = "",
    filter_options: dict | None = None,
) -> tuple[str, list]:
    """
    Build a WHERE clause and parameter list from filter criteria.

    All conditions reference only the ``cards`` table (aliased ``c``) and
    use subqueries for joins, so the clause works with or without the
    lateral print join.

    Parameters
    ----------
    text_query : str
        Free-text search for name, id, or rules text
    filter_options : dict, optional
        Property filters (see ``query_cards_filtered`` for format)

    Returns
    -------
    where_clause : str
        SQL fragment starting with ``WHERE`` or empty string
    params : list
        Positional parameters matching ``%s`` placeholders in the clause
    """
    conditions: list[str] = []
    params: list = []

    if text_query:
        conditions.append(
            "(c.name ILIKE %s ESCAPE '\\'"
            " OR c.card_id ILIKE %s ESCAPE '\\'"
            " OR c.rules_text ILIKE %s ESCAPE '\\')"
        )
        search_pattern = f"%{_escape_like(text_query)}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    if filter_options:
        for property_name, value in filter_options.items():
            if property_name == "legality":
                format_name, _statuses = value
                if format_name:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_legalities WHERE format_name = %s)"
                    )
                    params.append(format_name)
            elif property_name == "sets":
                if value:
                    conditions.append(
                        "c.card_id IN (SELECT p.card_id FROM prints p"
                        " JOIN l5r_sets s ON s.set_id = p.set_id WHERE s.set_name = ANY(%s))"
                    )
                    params.append(value)
            elif property_name == "decks":
                if value:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_decks"
                        " WHERE deck = ANY(%s::deck_type[]))"
                    )
                    params.append([d.title() for d in value])
            elif property_name == "types":
                if value:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_card_types"
                        " WHERE type = ANY(%s::card_type[]))"
                    )
                    params.append([t.title() for t in value])
            elif property_name == "clans":
                if value:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_clans WHERE lower(clan) = ANY(%s))"
                    )
                    params.append([c.lower() for c in value])
            elif property_name == "rarities":
                if value:
                    rarity_conditions = []
                    for rarity in value:
                        rarity_conditions.append("rarity ILIKE %s ESCAPE '\\'")
                        params.append(f"%{_escape_like(rarity)}%")
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM prints"
                        f" WHERE {' OR '.join(rarity_conditions)})"
                    )
            elif property_name == "keywords":
                if value:
                    for keyword in value:
                        conditions.append(
                            "c.card_id IN (SELECT card_id FROM card_keywords"
                            " WHERE lower(keyword) = lower(%s))"
                        )
                        params.append(keyword)
            elif property_name in _NUMERIC_STATS:
                if isinstance(value, tuple) and len(value) == 2:
                    min_val, max_val = value
                    if min_val is not None and max_val is not None:
                        conditions.append(f"c.{property_name} >= %s AND c.{property_name} <= %s")
                        params.extend([min_val, max_val])
                    elif min_val is not None:
                        conditions.append(f"c.{property_name} >= %s")
                        params.append(min_val)
                    elif max_val is not None:
                        conditions.append(f"c.{property_name} <= %s")
                        params.append(max_val)
            elif value is not None:
                if property_name not in _ALLOWED_COLUMNS:
                    logger.warning(f"Ignoring unknown filter column: {property_name}")
                    continue
                conditions.append(f"c.{property_name} = %s")
                params.append(value)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    return where_clause, params


def query_cards_filtered(
    text_query: str = "",
    filter_options: dict | None = None,
) -> list[dict]:
    """
    Query cards with dynamic SQL-based filtering.

    Returns all matching rows. For paginated access, use
    ``query_cards_page`` instead.

    Parameters
    ----------
    text_query : str
        Search query for card name or ID (case-insensitive)
    filter_options : dict, optional
        Dictionary of property filters. Keys are property names, values are
        constraints.  Special filters:
        - "legality": tuple of (format_name, list of statuses)
        - Other keys map directly to card table columns

    Returns
    -------
    cards : list of dict
        Card records matching all filter criteria, sorted by name
    """
    where_clause, params = _build_card_filter(text_query, filter_options)
    sql = f"{_CARD_SELECT} {where_clause} ORDER BY c.name"

    logger.debug(f"Executing filtered query with {len(params)} params")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            results = cur.fetchall()
            logger.debug(f"Retrieved {len(results)} cards from filtered query")
            return results


# Whitelist of sortable card columns. Keys are the public sort identifiers accepted by the API;
# values are the qualified SQL columns. Restricting ORDER BY to this map keeps the sort key
# injection-safe even though it is interpolated into the query string.
_SORT_COLUMNS = {
    "name": "c.name",
    "force": "c.force",
    "chi": "c.chi",
    "gold_cost": "c.gold_cost",
    "focus": "c.focus",
    "personal_honor": "c.personal_honor",
    "honor_requirement": "c.honor_requirement",
    "province_strength": "c.province_strength",
}


def _order_by_clause(sort: str, order: str) -> str:
    """Build a safe ``ORDER BY`` clause from a whitelisted sort key and direction.

    Numeric stats sort NULLs last (cards without the stat fall to the end in both directions) with a
    name tiebreaker for a stable order; an unknown key falls back to name.
    """
    column = _SORT_COLUMNS.get(sort, "c.name")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    if column == "c.name":
        return f"ORDER BY c.name {direction}"
    return f"ORDER BY {column} {direction} NULLS LAST, c.name ASC"


def query_cards_page(
    text_query: str = "",
    filter_options: dict | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
    sort: str = "name",
    order: str = "asc",
) -> tuple[list[dict], int]:
    """
    Query a single page of cards with SQL-level pagination.

    Runs a ``COUNT(*)`` query (without the lateral join) and a paginated
    data query in the same connection for consistency and efficiency.

    Parameters
    ----------
    text_query : str
        Search query for card name or ID (case-insensitive)
    filter_options : dict, optional
        Property filters (same format as ``query_cards_filtered``)
    limit : int
        Maximum rows to return (default 100)
    offset : int
        Number of rows to skip (default 0)
    sort : str
        Column to order by, one of the keys in ``_SORT_COLUMNS``. An unknown key falls back to name.
        Default 'name'.
    order : str
        Sort direction, ``'asc'`` or ``'desc'``. Default 'asc'.

    Returns
    -------
    cards : list of dict
        One page of card records, ordered by the requested sort
    total : int
        Total number of cards matching the filters (for pagination metadata)
    """
    where_clause, params = _build_card_filter(text_query, filter_options)

    count_sql = f"SELECT COUNT(*) AS n FROM cards c {where_clause}"
    data_sql = f"{_CARD_SELECT} {where_clause} {_order_by_clause(sort, order)} LIMIT %s OFFSET %s"
    data_params = params + [limit, offset]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["n"]

            cur.execute(data_sql, data_params)
            cards = cur.fetchall()

    logger.debug(
        "Page query: %d cards returned, %d total (limit=%d, offset=%d)",
        len(cards),
        total,
        limit,
        offset,
    )
    return cards, total


def count_cards_filtered(
    text_query: str = "",
    filter_options: dict | None = None,
) -> int:
    """
    Count cards matching filters without fetching row data.

    Skips the lateral print join, making it significantly cheaper than
    ``query_cards_filtered`` when only the count is needed.

    Parameters
    ----------
    text_query : str
        Search query for card name or ID (case-insensitive)
    filter_options : dict, optional
        Property filters (same format as ``query_cards_filtered``)

    Returns
    -------
    count : int
        Number of matching cards
    """
    where_clause, params = _build_card_filter(text_query, filter_options)
    sql = f"SELECT COUNT(*) AS n FROM cards c {where_clause}"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()["n"]


def query_random_cards(
    count: int,
    deck_filter: str | None = None,
) -> list[dict]:
    """
    Fetch random cards using SQL-level sampling.

    Parameters
    ----------
    count : int
        Number of random cards to return
    deck_filter : str, optional
        Limit to a specific deck type (e.g. 'FATE', 'DYNASTY')

    Returns
    -------
    cards : list of dict
        Randomly selected card records
    """
    conditions: list[str] = []
    params: list = []

    if deck_filter:
        conditions.append(
            "EXISTS (SELECT 1 FROM card_decks d WHERE d.card_id = c.card_id AND d.deck = %s::deck_type)"
        )
        params.append(deck_filter)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"{_CARD_SELECT} {where_clause} ORDER BY RANDOM() LIMIT %s"
    params.append(count)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
