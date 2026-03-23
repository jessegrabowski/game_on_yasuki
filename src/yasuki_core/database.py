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


def query_all_cards() -> list[dict]:
    """
    Fetch all cards from database with their primary print information.

    Returns
    -------
    cards : list of dict
        List of card records with fields: id, name, deck, type, clan,
        rules_text, and image_path from the first print if available
    """
    logger.debug("Querying all cards from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    c.id,
                    c.name,
                    c.extended_title,
                    c.deck::text as side,
                    c.type::text as type,
                    c.clan,
                    c.rules_text as text,
                    c.gold_cost,
                    c.focus,
                    c.force,
                    c.chi,
                    c.honor_requirement,
                    c.personal_honor,
                    c.gold_production,
                    c.province_strength,
                    c.starting_honor,
                    c.is_unique,
                    c.extra,
                    p.image_path
                FROM cards c
                LEFT JOIN LATERAL (
                    SELECT image_path
                    FROM prints
                    WHERE prints.card_id = c.id
                    ORDER BY print_id
                    LIMIT 1
                ) p ON true
                ORDER BY c.name
            """)
            results = cur.fetchall()
            logger.debug(f"Retrieved {len(results)} cards from database")
            return results


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
        conditions.append("c.deck = %s::deck_type")
        params.append(deck_filter.upper())

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"""
        SELECT
            c.id,
            c.name,
            c.extended_title,
            c.deck::text as side,
            c.type::text as type,
            c.clan,
            c.rules_text as text,
            c.gold_cost,
            c.focus,
            c.force,
            c.chi,
            c.honor_requirement,
            c.personal_honor,
            c.gold_production,
            c.province_strength,
            c.starting_honor,
            c.is_unique,
            c.extra,
            p.image_path
        FROM cards c
        LEFT JOIN LATERAL (
            SELECT image_path
            FROM prints
            WHERE prints.card_id = c.id
            ORDER BY print_id
            LIMIT 1
        ) p ON true
        {where_clause}
        ORDER BY c.name
    """

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
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
                    c.id,
                    c.name,
                    c.extended_title,
                    c.deck::text as side,
                    c.type::text as type,
                    c.clan,
                    c.rules_text as text,
                    c.gold_cost,
                    c.focus,
                    c.force,
                    c.chi,
                    c.honor_requirement,
                    c.personal_honor,
                    c.gold_production,
                    c.province_strength,
                    c.starting_honor,
                    c.is_unique,
                    p.print_id,
                    p.set_name,
                    p.rarity,
                    p.artist,
                    p.image_path,
                    p.flavor_text
                FROM cards c
                JOIN prints p ON c.id = p.card_id
                ORDER BY c.name, p.set_name
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
            cur.execute(
                """
                SELECT
                    c.id,
                    c.name,
                    c.deck::text as side,
                    c.type::text as type,
                    c.clan,
                    c.rules_text as text,
                    c.gold_cost,
                    c.focus,
                    c.force,
                    c.chi,
                    c.honor_requirement,
                    c.personal_honor,
                    c.gold_production,
                    c.province_strength,
                    c.starting_honor,
                    c.is_unique,
                    p.image_path
                FROM cards c
                LEFT JOIN LATERAL (
                    SELECT image_path
                    FROM prints
                    WHERE prints.card_id = c.id
                    ORDER BY print_id
                    LIMIT 1
                ) p ON true
                WHERE c.id = %s
            """,
                (card_id,),
            )
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
                    print_id,
                    card_id,
                    set_name,
                    rarity,
                    artist,
                    image_path,
                    flavor_text
                FROM prints
                WHERE card_id = %s
                ORDER BY set_name
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
                """
                SELECT
                    c.id, c.name, c.extended_title,
                    c.deck::text AS side, c.type::text AS type,
                    c.clan, c.is_unique,
                    c.rules_text AS text,
                    c.force, c.chi, c.gold_cost, c.focus,
                    c.honor_requirement, c.personal_honor,
                    c.gold_production, c.province_strength, c.starting_honor
                FROM cards c
                WHERE lower(c.name) = ANY(%s) OR lower(c.extended_title) = ANY(%s)
                ORDER BY c.name
                """,
                (lower_names, lower_names),
            )
            cards = cur.fetchall()

            if not cards:
                return []

            card_ids = [c["id"] for c in cards]
            cur.execute(
                """
                SELECT print_id, card_id, set_name, image_path, flavor_text
                FROM prints
                WHERE card_id = ANY(%s)
                ORDER BY print_id
                """,
                (card_ids,),
            )
            prints_by_card: dict[str, list] = {}
            for row in cur.fetchall():
                prints_by_card.setdefault(row["card_id"], []).append(row)

            for card in cards:
                card["prints"] = prints_by_card.get(card["id"], [])

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


def query_cards_by_legality(format_name: str, statuses: list[str] | None = None) -> list[str]:
    """
    Fetch card IDs that match legality criteria for a format.

    Parameters
    ----------
    format_name : str
        Format name to filter by
    statuses : list of str, optional
        List of legality statuses to include (e.g., ['legal', 'not_legal']).
        If None, includes all cards with any legality entry for the format.

    Returns
    -------
    card_ids : list of str
        List of card IDs matching the criteria
    """
    logger.debug(f"Querying cards for format '{format_name}' with statuses {statuses}")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if statuses:
                cur.execute(
                    """
                    SELECT card_id
                    FROM card_legalities
                    WHERE format_name = %s AND status::text = ANY(%s)
                    ORDER BY card_id
                    """,
                    (format_name, statuses),
                )
            else:
                cur.execute(
                    """
                    SELECT card_id
                    FROM card_legalities
                    WHERE format_name = %s
                    ORDER BY card_id
                    """,
                    (format_name,),
                )
            results = [row["card_id"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} cards for format '{format_name}'")
            return results


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
                SELECT DISTINCT set_name
                FROM prints
                WHERE set_name IS NOT NULL AND set_name != ''
                ORDER BY set_name
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
            cur.execute("""
                SELECT DISTINCT deck::text
                FROM cards
                WHERE deck IS NOT NULL
                ORDER BY deck
            """)
            results = [row["deck"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} deck types from database")
            return results


def query_all_clans() -> list[str]:
    """
    Fetch all unique individual clans from cards.

    Cards may have multiple clans stored as comma-separated values.
    This splits them and returns each unique clan individually.

    Returns
    -------
    clans : list of str
        List of clan names, sorted alphabetically
    """
    logger.debug("Querying all clans from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT trim(unnest(string_to_array(clan, ','))) AS clan
                FROM cards
                WHERE clan IS NOT NULL AND clan != ''
                ORDER BY clan
            """)
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
            cur.execute("""
                SELECT DISTINCT type::text
                FROM cards
                WHERE type IS NOT NULL
                ORDER BY type
            """)
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
                SELECT DISTINCT type::text
                FROM cards
                WHERE type IS NOT NULL
                AND deck = ANY(%s::deck_type[])
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
            # Find card types with non-NULL values for this stat
            cur.execute(f"""
                SELECT DISTINCT type::text
                FROM cards
                WHERE {stat_name} IS NOT NULL
                ORDER BY type
            """)
            types = [row["type"] for row in cur.fetchall()]

            # Find deck types with non-NULL values for this stat
            cur.execute(f"""
                SELECT DISTINCT deck::text
                FROM cards
                WHERE {stat_name} IS NOT NULL
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
                        ARRAY_AGG(DISTINCT type::text ORDER BY type::text) FILTER (WHERE type IS NOT NULL) as types,
                        ARRAY_AGG(DISTINCT deck::text ORDER BY deck::text) FILTER (WHERE deck IS NOT NULL) as decks
                    FROM cards
                    WHERE {stat} IS NOT NULL
                """)
                row = cur.fetchone()
                types = set(row["types"]) if row["types"] else set()
                decks = set(row["decks"]) if row["decks"] else set()
                mappings[stat] = (types, decks)

    logger.debug(f"Retrieved mappings for {len(mappings)} stats")
    return mappings


def query_sets_by_format(format_name: str, statuses: list[str] | None = None) -> list[str]:
    """
    Fetch unique set names that belong to a specific format's arc/era.

    For arc-specific formats (e.g., "Clan Wars (Imperial)"), only returns sets
    that are actually part of that format's arc.

    For cross-era formats (Modern, Legacy), returns all sets with legal cards.

    Parameters
    ----------
    format_name : str
        Format name to filter by
    statuses : list of str, optional
        List of legality statuses to include (e.g., ['legal', 'not_legal']).
        If None, includes all cards with any legality entry for the format.

    Returns
    -------
    sets : list of str
        List of unique set names, sorted alphabetically
    """
    logger.debug(f"Querying sets for format '{format_name}' with statuses {statuses}")

    # Cross-era formats that include cards from multiple arcs
    cross_era_formats = {"Modern", "Legacy", "Not Legal (Proxy)", "Unreleased"}

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if format_name in cross_era_formats:
                # For cross-era formats, return all sets with cards legal in the format
                if statuses:
                    cur.execute(
                        """
                        SELECT DISTINCT p.set_name
                        FROM prints p
                        WHERE p.card_id IN (
                            SELECT card_id
                            FROM card_legalities
                            WHERE format_name = %s AND status::text = ANY(%s)
                        )
                        AND p.set_name IS NOT NULL AND p.set_name != ''
                        ORDER BY p.set_name
                        """,
                        (format_name, statuses),
                    )
                else:
                    cur.execute(
                        """
                        SELECT DISTINCT p.set_name
                        FROM prints p
                        WHERE p.card_id IN (
                            SELECT card_id
                            FROM card_legalities
                            WHERE format_name = %s
                        )
                        AND p.set_name IS NOT NULL AND p.set_name != ''
                        ORDER BY p.set_name
                        """,
                        (format_name,),
                    )
            else:
                # For arc-specific formats, only return sets from that arc
                if statuses:
                    cur.execute(
                        """
                        SELECT DISTINCT p.set_name
                        FROM prints p
                        INNER JOIN l5r_sets s ON p.set_name = s.set_name
                        WHERE p.card_id IN (
                            SELECT card_id
                            FROM card_legalities
                            WHERE format_name = %s AND status::text = ANY(%s)
                        )
                        AND p.set_name IS NOT NULL AND p.set_name != ''
                        AND (
                            -- Match sets where the arc contains part of the format name
                            -- or the format name contains the arc name
                            s.arc ILIKE '%%' || SPLIT_PART(%s, ' (', 1) || '%%'
                            OR %s ILIKE '%%' || s.arc || '%%'
                            OR s.arc = SPLIT_PART(%s, ' (', 1)
                        )
                        ORDER BY p.set_name
                        """,
                        (format_name, statuses, format_name, format_name, format_name),
                    )
                else:
                    cur.execute(
                        """
                        SELECT DISTINCT p.set_name
                        FROM prints p
                        INNER JOIN l5r_sets s ON p.set_name = s.set_name
                        WHERE p.card_id IN (
                            SELECT card_id
                            FROM card_legalities
                            WHERE format_name = %s
                        )
                        AND p.set_name IS NOT NULL AND p.set_name != ''
                        AND (
                            -- Match sets where the arc contains part of the format name
                            -- or the format name contains the arc name
                            s.arc ILIKE '%%' || SPLIT_PART(%s, ' (', 1) || '%%'
                            OR %s ILIKE '%%' || s.arc || '%%'
                            OR s.arc = SPLIT_PART(%s, ' (', 1)
                        )
                        ORDER BY p.set_name
                        """,
                        (format_name, format_name, format_name, format_name),
                    )
            results = [row["set_name"] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} sets for format '{format_name}'")
            return results


_CARD_SELECT = """
    SELECT
        c.id,
        c.name,
        c.extended_title,
        c.deck::text as side,
        c.type::text as type,
        c.clan,
        c.rules_text as text,
        c.gold_cost,
        c.focus,
        c.force,
        c.chi,
        c.honor_requirement,
        c.personal_honor,
        c.gold_production,
        c.province_strength,
        c.starting_honor,
        c.is_unique,
        c.extra,
        p.image_path
    FROM cards c
    LEFT JOIN LATERAL (
        SELECT image_path
        FROM prints
        WHERE prints.card_id = c.id
        ORDER BY print_id
        LIMIT 1
    ) p ON true"""

_ALLOWED_COLUMNS = {
    "deck",
    "type",
    "clan",
    "is_unique",
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
            " OR c.id ILIKE %s ESCAPE '\\'"
            " OR c.rules_text ILIKE %s ESCAPE '\\')"
        )
        search_pattern = f"%{_escape_like(text_query)}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    if filter_options:
        for property_name, value in filter_options.items():
            if property_name == "legality":
                format_name, statuses = value
                if format_name:
                    if statuses:
                        conditions.append(
                            """
                            c.id IN (
                                SELECT card_id
                                FROM card_legalities
                                WHERE format_name = %s AND status::text = ANY(%s)
                            )
                            """
                        )
                        params.extend([format_name, statuses])
                    else:
                        conditions.append(
                            """
                            c.id IN (
                                SELECT card_id
                                FROM card_legalities
                                WHERE format_name = %s
                            )
                            """
                        )
                        params.append(format_name)
                elif statuses:
                    conditions.append(
                        """
                        c.id IN (
                            SELECT DISTINCT card_id
                            FROM card_legalities
                            WHERE status::text = ANY(%s)
                        )
                        """
                    )
                    params.append(statuses)

            elif property_name == "sets":
                set_list = value
                if set_list:
                    conditions.append(
                        """
                        c.id IN (
                            SELECT DISTINCT card_id
                            FROM prints
                            WHERE set_name = ANY(%s)
                        )
                        """
                    )
                    params.append(set_list)
            elif property_name == "decks":
                deck_list = value
                if deck_list:
                    conditions.append("c.deck = ANY(%s::deck_type[])")
                    params.append(deck_list)
            elif property_name == "types":
                type_list = value
                if type_list:
                    conditions.append("c.type = ANY(%s::card_type[])")
                    params.append([t.title() for t in type_list])
            elif property_name == "clans":
                clan_list = value
                if clan_list:
                    clan_conditions = []
                    for clan in clan_list:
                        clan_conditions.append("c.clan ILIKE %s ESCAPE '\\'")
                        params.append(f"%{_escape_like(clan)}%")
                    conditions.append(f"({' OR '.join(clan_conditions)})")
            elif property_name == "rarities":
                rarity_list = value
                if rarity_list:
                    rarity_conditions = []
                    for rarity in rarity_list:
                        rarity_conditions.append("p2.rarity ILIKE %s ESCAPE '\\'")
                        params.append(f"%{_escape_like(rarity)}%")
                    conditions.append(
                        f"""
                        c.id IN (
                            SELECT DISTINCT card_id
                            FROM prints p2
                            WHERE {" OR ".join(rarity_conditions)}
                        )
                        """
                    )
            elif property_name == "keywords":
                keyword_list = value
                if keyword_list:
                    for keyword in keyword_list:
                        conditions.append(
                            """
                            c.id IN (
                                SELECT card_id
                                FROM card_keywords
                                WHERE lower(keyword) = lower(%s)
                            )
                            """
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
                if property_name == "deck":
                    conditions.append("c.deck = %s::deck_type")
                elif property_name == "type":
                    conditions.append("c.type = %s::card_type")
                else:
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


def query_cards_page(
    text_query: str = "",
    filter_options: dict | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
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

    Returns
    -------
    cards : list of dict
        One page of card records, sorted by name
    total : int
        Total number of cards matching the filters (for pagination metadata)
    """
    where_clause, params = _build_card_filter(text_query, filter_options)

    count_sql = f"SELECT COUNT(*) AS n FROM cards c {where_clause}"
    data_sql = f"{_CARD_SELECT} {where_clause} ORDER BY c.name LIMIT %s OFFSET %s"
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
        conditions.append("c.deck = %s::deck_type")
        params.append(deck_filter.upper())

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    sql = f"{_CARD_SELECT} {where_clause} ORDER BY RANDOM() LIMIT %s"
    params.append(count)

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
