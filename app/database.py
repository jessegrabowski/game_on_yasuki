import os
from contextlib import contextmanager
from collections.abc import Generator
import psycopg2
from psycopg2.extras import RealDictCursor

import logging

logger = logging.getLogger(__name__)


def get_connection_string() -> str:
    """
    Get PostgreSQL connection string from environment or use default.

    Returns
    -------
    dsn : str
        PostgreSQL connection string
    """
    return os.environ.get("L5R_DATABASE_URL", "postgresql://localhost/l5r")


@contextmanager
def get_db_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Context manager for database connections.

    Yields
    ------
    conn : psycopg2 connection
        Database connection with autocommit enabled
    """
    conn = psycopg2.connect(get_connection_string())
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            results = [dict(row) for row in cur.fetchall()]
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
        conditions.append("(c.name ILIKE %s OR c.rules_text ILIKE %s)")
        search_pattern = f"%{query}%"
        params.extend([search_pattern, search_pattern])

    if deck_filter:
        conditions.append("c.deck::text = %s")
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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            results = [dict(row) for row in cur.fetchall()]
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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            row = cur.fetchone()
            return dict(row) if row else None


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
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            return [dict(row) for row in cur.fetchall()]


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
            results = [row[0] for row in cur.fetchall()]
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
            results = [row[0] for row in cur.fetchall()]
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
            results = [row[0] for row in cur.fetchall()]
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
            results = [row[0] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} deck types from database")
            return results


def query_all_clans() -> list[str]:
    """
    Fetch all unique clans from cards.

    Returns
    -------
    clans : list of str
        List of clan names, sorted alphabetically
    """
    logger.debug("Querying all clans from database")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT clan
                FROM cards
                WHERE clan IS NOT NULL AND clan != ''
                ORDER BY clan
            """)
            results = [row[0] for row in cur.fetchall()]
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
            results = [row[0] for row in cur.fetchall()]
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
            results = [row[0] for row in cur.fetchall()]
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
                AND deck::text = ANY(%s)
                ORDER BY type
            """,
                (deck_types,),
            )
            results = [row[0] for row in cur.fetchall()]
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
                "force": (row[0] or 0, row[1] or 20),
                "chi": (row[2] or -2, row[3] or 15),
                "honor_requirement": (row[4] or 0, row[5] or 40),
                "gold_cost": (row[6] or 0, row[7] or 20),
                "personal_honor": (row[8] or 0, row[9] or 6),
                "province_strength": (row[10] or -1, row[11] or 20),
                "gold_production": (row[12] or -1, row[13] or 8),
                "starting_honor": (row[14] or -20, row[15] or 15),
                "focus": (row[16] or 0, row[17] or 5),
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
            types = [row[0] for row in cur.fetchall()]

            # Find deck types with non-NULL values for this stat
            cur.execute(f"""
                SELECT DISTINCT deck::text
                FROM cards
                WHERE {stat_name} IS NOT NULL
                ORDER BY deck
            """)
            decks = [row[0] for row in cur.fetchall()]

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
                types = set(row[0]) if row[0] else set()
                decks = set(row[1]) if row[1] else set()
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
            results = [row[0] for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} sets for format '{format_name}'")
            return results


def query_cards_filtered(
    text_query: str = "",
    filter_options: dict | None = None,
) -> list[dict]:
    """
    Query cards with dynamic SQL-based filtering.

    Builds SQL query based on filter options for optimal database performance.
    Supports arbitrary combinations of card properties.

    Parameters
    ----------
    text_query : str
        Search query for card name or ID (case-insensitive)
    filter_options : dict, optional
        Dictionary of property filters. Keys are property names, values are constraints.
        Special filters:
        - "legality": tuple of (format_name, list of statuses)
        - Other keys map directly to card table columns

    Returns
    -------
    cards : list of dict
        Card records matching all filter criteria, sorted by name

    Examples
    --------
    # Filter by legality
    query_cards_filtered(filter_options={"legality": ("Ivory Edition", ["legal"])})

    # Filter by clan and type
    query_cards_filtered(filter_options={"clan": "Crane", "type": "personality"})

    # Combine text search and filters
    query_cards_filtered("Doji", filter_options={"clan": "Crane"})
    """
    conditions = []
    params = []

    # Base query selecting card data with first print image
    base_query = """
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
    """

    # Apply text search
    if text_query:
        conditions.append("(c.name ILIKE %s OR c.id ILIKE %s)")
        search_pattern = f"%{text_query}%"
        params.extend([search_pattern, search_pattern])

    # Apply property filters
    if filter_options:
        for property_name, value in filter_options.items():
            if property_name == "legality":
                # Special handling for legality filter
                format_name, statuses = value

                if format_name:
                    # Filter by specific format
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
                else:
                    # No format specified - filter by legality status across ALL formats
                    # Find cards that have the specified status in at least one format
                    if statuses:
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
                    # If no statuses and no format, don't add any condition

            elif property_name == "sets":
                # Special handling for set filter (multi-select)
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
                # Special handling for deck filter (multi-select)
                deck_list = value
                if deck_list:
                    conditions.append("c.deck::text = ANY(%s)")
                    params.append(deck_list)
            elif property_name == "types":
                # Special handling for type filter (multi-select)
                type_list = value
                if type_list:
                    conditions.append("c.type::text = ANY(%s)")
                    params.append(type_list)
            elif property_name == "clans":
                # Special handling for clan filter (multi-select)
                # Clans can be comma-separated in the database, so we need to check if any selected clan appears in the field
                clan_list = value
                if clan_list:
                    # Build OR conditions for each clan (handles comma-separated values)
                    clan_conditions = []
                    for clan in clan_list:
                        clan_conditions.append("c.clan ILIKE %s")
                        params.append(f"%{clan}%")
                    conditions.append(f"({' OR '.join(clan_conditions)})")
            elif property_name == "rarities":
                # Special handling for rarity filter (multi-select)
                # Rarities are in the prints table and can be comma-separated
                rarity_list = value
                if rarity_list:
                    # Build OR conditions for each rarity (handles comma-separated values)
                    rarity_conditions = []
                    for rarity in rarity_list:
                        rarity_conditions.append("p2.rarity ILIKE %s")
                        params.append(f"%{rarity}%")
                    conditions.append(
                        f"""
                        c.id IN (
                            SELECT DISTINCT card_id
                            FROM prints p2
                            WHERE {" OR ".join(rarity_conditions)}
                        )
                        """
                    )
            elif property_name in (
                "force",
                "chi",
                "honor_requirement",
                "gold_cost",
                "personal_honor",
                "province_strength",
                "gold_production",
                "starting_honor",
                "focus",
            ):
                # Handle range filters for numeric statistics
                # Value is a tuple: (min_val, max_val) where either can be None
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
                # Direct column comparison
                # Cast enum types to text for comparison
                if property_name in ("deck", "type"):
                    conditions.append(f"c.{property_name}::text = %s")
                else:
                    conditions.append(f"c.{property_name} = %s")
                params.append(value)

    # Build WHERE clause
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Complete query
    sql = f"{base_query} {where_clause} ORDER BY c.name"

    logger.debug(f"Executing filtered query with {len(conditions)} conditions")
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            results = [dict(row) for row in cur.fetchall()]
            logger.debug(f"Retrieved {len(results)} cards from filtered query")
            return results
