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


def apply_sslmode(dsn: str) -> str:
    """Append an ``sslmode`` to a DSN aimed at a public host, leaving private/loopback hosts alone.

    Verify the server certificate and hostname (``sslmode=verify-full``) with the CA bundle when
    ``YASUKI_DB_SSL_ROOT_CERT`` points at one; otherwise require encryption without authentication
    (``sslmode=require``). A DSN that already sets ``sslmode``, or that targets a private/loopback
    host, is returned unchanged.

    Parameters
    ----------
    dsn : str
        The PostgreSQL connection string to augment.

    Returns
    -------
    dsn : str
        The connection string, with an ``sslmode`` appended when warranted.
    """
    if "sslmode" in dsn or _is_private_dsn(dsn):
        return dsn
    separator = "&" if "?" in dsn else "?"
    root_cert = os.environ.get("YASUKI_DB_SSL_ROOT_CERT")
    if root_cert:
        return f"{dsn}{separator}sslmode=verify-full&sslrootcert={root_cert}"
    return f"{dsn}{separator}sslmode=require"


def get_connection_string() -> str:
    """
    Get PostgreSQL connection string from environment or use default.

    Checks YASUKI_DATABASE_URL first, then DATABASE_URL (used by Railway and
    other PaaS providers), then falls back to localhost. Public hosts get an ``sslmode`` appended
    (see ``apply_sslmode``).

    Returns
    -------
    dsn : str
        PostgreSQL connection string
    """
    dsn = os.environ.get(
        "YASUKI_DATABASE_URL", os.environ.get("DATABASE_URL", "postgresql://localhost/yasuki")
    )
    return apply_sslmode(dsn)


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


# Shared card columns: card-level fields plus multi-valued clan/type/deck/keyword text arrays.
_CARD_COLUMNS = """
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
        c.story,
        c.gold_cost, c.focus, c.force, c.chi,
        c.honor_requirement, c.personal_honor, c.gold_production,
        c.province_strength, c.starting_honor, c.back_card_id,
        c.is_unique, c.is_proxy, c.is_banned, c.extra,
        img.image_path, img.default_print_id, img.default_set_slug
    FROM cards c"""

# Joins each card to its back face so cross-face search predicates can reach the back's columns. The
# COUNT queries must carry the same join as the data select, or a `back.<col>` predicate 500s.
_CROSS_FACE_JOIN = "LEFT JOIN cards back ON back.card_id = c.back_card_id"


def _card_select(active_format: str | None = None) -> tuple[str, list]:
    """
    Build the shared card SELECT and its leading parameters.

    The default print — the one supplying ``image_path`` / ``default_print_id`` — is the card's
    representative printing. With an active arc/format filter, it is the earliest printing from that
    format's arc; for a card carried into the format by rotation with no printing in that arc, it is
    the most recent printing whose own arc was already legal as of the format. Without a filter, or
    for a format with no era (Legacy/Modern), it is the earliest printing by release date.
    ``print_id`` is the final stable tiebreaker.

    Parameters
    ----------
    active_format : str, optional
        Format name or its short block alias (e.g. ``"shattered"``) whose arc and era the default
        print should reflect. When omitted, the default print is chosen by release date alone.

    Returns
    -------
    sql : str
        The SELECT up to and including the lateral image join, ready to append a WHERE clause to.
    select_params : list
        Positional parameters for the format-resolution join, to be prepended to the WHERE-clause
        params.
    """
    if active_format:
        # Resolve the active format once (by name or block alias, matching whatever the search
        # parser emitted) so the print ordering below can reference its arc and era.
        format_join = (
            "\n    LEFT JOIN LATERAL (SELECT f.arc, f.legal_from FROM formats f"
            " WHERE lower(f.name) = lower(%s) OR lower(f.block) = lower(%s) LIMIT 1) af ON true"
        )
        # Keys: in-arc first; earliest in-arc / newest in-era otherwise; future-arc prints last.
        order_clause = (
            "ORDER BY (s.arc IS DISTINCT FROM af.arc),"
            " CASE WHEN s.arc IS NOT DISTINCT FROM af.arc OR af.legal_from IS NULL"
            " THEN s.release_date END ASC NULLS LAST,"
            " (COALESCE((SELECT min(f2.legal_from) FROM formats f2 WHERE f2.arc = s.arc),"
            " '-infinity'::date) > af.legal_from),"
            " s.release_date DESC NULLS LAST, p.print_id, pi.image_index"
        )
        select_params = [active_format, active_format]
    else:
        format_join = ""
        order_clause = "ORDER BY s.release_date NULLS LAST, p.print_id, pi.image_index"
        select_params = []

    sql = f"""{_CARD_COLUMNS}{format_join}
    LEFT JOIN LATERAL (
        SELECT pi.path AS image_path, p.print_id AS default_print_id, s.set_slug AS default_set_slug
        FROM prints p
        JOIN print_images pi ON pi.print_id = p.print_id AND pi.role = 'front'
        LEFT JOIN l5r_sets s ON s.set_id = p.set_id
        WHERE p.card_id = c.card_id
        {order_clause}
        LIMIT 1
    ) img ON true
    {_CROSS_FACE_JOIN}"""
    return sql, select_params


def query_all_cards() -> list[dict]:
    """Fetch every card with its multi-valued attributes and front image, ordered by name."""
    select_sql, _ = _card_select()
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(f"{select_sql} WHERE NOT c.is_back ORDER BY {_NAME_TIEBREAK}")
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

    select_sql, _ = _card_select()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{select_sql} {where_clause} ORDER BY {_NAME_TIEBREAK}", params)
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
    select_sql, _ = _card_select()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"{select_sql} WHERE c.card_id = %s", (card_id,))
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
                    p.print_id, p.card_id, s.set_name, s.set_slug, p.rarity, p.artist,
                    front.path AS image_path,
                    COALESCE(back.path, pback.path) AS back_image_path,
                    p.flavor_text,
                    COALESCE(bp.flavor_text, p.back_flavor) AS back_flavor_text,
                    p.back_title
                FROM prints p
                JOIN l5r_sets s ON s.set_id = p.set_id
                JOIN cards c ON c.card_id = p.card_id
                LEFT JOIN print_images front
                    ON front.print_id = p.print_id AND front.role = 'front' AND front.size = 'master'
                -- A flip card's back image/flavor live on the back card's matching printing; a
                -- printing's own special back (scroll / clan mon) is a role='back' image on it.
                LEFT JOIN prints bp ON bp.card_id = c.back_card_id AND bp.printing_id = p.printing_id
                LEFT JOIN print_images back
                    ON back.print_id = bp.print_id AND back.role = 'front' AND back.size = 'master'
                LEFT JOIN print_images pback
                    ON pback.print_id = p.print_id AND pback.role = 'back' AND pback.size = 'master'
                WHERE p.card_id = %s
                ORDER BY s.release_date NULLS LAST, p.print_id
            """,
                (card_id,),
            )
            return cur.fetchall()


def get_card_revisions(card_id: str) -> list[dict]:
    """
    Fetch a card's rules-text revision history, oldest first.

    Only errata'd cards have rows; an unerrata'd card returns an empty list. Revision 0 is the
    original printing text and the highest index is the current version (also mirrored onto the cards
    row). This backs the card page's errata badge and "what did it used to say" history.

    Parameters
    ----------
    card_id : str
        Card ID.

    Returns
    -------
    revisions : list of dict
        Revisions ordered by revision_index, each with its effective_date, source, rules_text, stats,
        image_path, and notes.
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT revision_index, effective_date, source, source_url, rules_text, stats,
                       image_path, notes
                FROM card_revisions
                WHERE card_id = %s
                ORDER BY revision_index
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
    select_sql, _ = _card_select()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"{select_sql} "
                "WHERE (lower(c.name) = ANY(%s) OR lower(c.extended_title) = ANY(%s)) "
                "AND NOT c.is_back "
                "ORDER BY split_part(c.name, ',', 1) ASC, c.experience ASC, c.extended_title ASC",
                (lower_names, lower_names),
            )
            cards = cur.fetchall()

            if not cards:
                return []

            card_ids = [c["card_id"] for c in cards]
            cur.execute(
                """
                SELECT p.print_id, p.card_id, s.set_name, pi.path AS image_path,
                    COALESCE(back.path, pback.path) AS back_image_path, p.flavor_text
                FROM prints p
                JOIN l5r_sets s ON s.set_id = p.set_id
                JOIN cards c ON c.card_id = p.card_id
                LEFT JOIN print_images pi
                    ON pi.print_id = p.print_id AND pi.role = 'front' AND pi.size = 'master'
                LEFT JOIN prints bp ON bp.card_id = c.back_card_id AND bp.printing_id = p.printing_id
                LEFT JOIN print_images back
                    ON back.print_id = bp.print_id AND back.role = 'front' AND back.size = 'master'
                LEFT JOIN print_images pback
                    ON pback.print_id = p.print_id AND pback.role = 'back' AND pback.size = 'master'
                WHERE p.card_id = ANY(%s)
                ORDER BY s.release_date NULLS LAST, p.print_id
                """,
                (card_ids,),
            )
            prints_by_card: dict[str, list] = {}
            for row in cur.fetchall():
                prints_by_card.setdefault(row["card_id"], []).append(row)

            for card in cards:
                card["prints"] = prints_by_card.get(card["card_id"], [])

            return cards


def all_card_ids() -> set[str]:
    """Every card id in the card database — the valid-id universe for deck-storage integrity checks.

    Returns
    -------
    card_ids : set of str
        All ids in ``cards``, including back faces, so any id that genuinely exists counts as known.
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT card_id FROM cards")
        return {row["card_id"] for row in cur.fetchall()}


def card_display_names(card_ids: set[str]) -> dict[str, str]:
    """Map each card id to its display name (extended title, else name).

    Used to re-label art-swap donors when rendering a stored deck back to YAML, since deck_cards
    keeps a donor's id but not its name.

    Parameters
    ----------
    card_ids : set of str
        The ids to resolve. An empty set yields an empty map without touching the database.

    Returns
    -------
    names : dict mapping str to str
        Card id to display name, omitting any id absent from the card database.
    """
    if not card_ids:
        return {}
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT card_id, COALESCE(extended_title, name) AS display "
            "FROM cards WHERE card_id = ANY(%s)",
            (list(card_ids),),
        )
        return {row["card_id"]: row["display"] for row in cur.fetchall()}


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


def query_formats_ordered() -> list[dict]:
    """Fetch formats with their chronological ``legal_from``, arcs oldest-first then non-arc formats.

    Returns
    -------
    formats : list of dict
        Each row has ``name`` and ``legal_from`` (None for formats outside the storyline timeline,
        which sort last).
    """
    with get_db_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, legal_from FROM formats ORDER BY legal_from NULLS LAST, name")
        return cur.fetchall()


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


# Comparison operators allowed in a `format>diamond` or `set>=ge`-style search, mapped to the SQL
# they emit. The map both whitelists the operator (keeping it injection-safe when interpolated) and
# excludes the exact operators, which take a different code path.
_RANGE_OPS = {">": ">", ">=": ">=", "<": "<", "<=": "<="}


def _active_format(filter_options: dict | None) -> str | None:
    """
    Resolve the single active format whose arc should bias default-print selection.

    An exact ``format:``/``arc:`` search token or the deck-builder format dropdown pins one format;
    inequality ranges, multiple specs, or no format filter leave it unresolved.

    Parameters
    ----------
    filter_options : dict or None
        The filter dictionary passed to ``_build_card_filter``.

    Returns
    -------
    active_format : str or None
        A format name or block alias, or None when no single format is in effect.
    """
    if not filter_options:
        return None
    specs = filter_options.get("format_filters")
    if specs and len(specs) == 1 and specs[0][0] in (":", "="):
        return specs[0][1]
    legality = filter_options.get("legality")
    if legality and legality[0]:
        return legality[0]
    return None


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

    # A back face is never a standalone result; a search reaches it through its front via the
    # cross-face conditions below, which consult the joined `back` row.
    conditions.append("NOT c.is_back")

    if text_query:
        conditions.append(
            "(c.name ILIKE %s ESCAPE '\\'"
            " OR c.card_id ILIKE %s ESCAPE '\\'"
            " OR (c.rules_text || ' ' || COALESCE(back.rules_text, '')) ILIKE %s ESCAPE '\\')"
        )
        search_pattern = f"%{_escape_like(text_query)}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    if filter_options:
        for property_name, value in filter_options.items():
            if property_name == "include":
                continue  # consumed by the default-visibility filter below, not a column condition
            elif property_name == "all":
                continue  # the match-everything predicate adds no constraints
            elif property_name == "_unknown_fields":
                # An unrecognized search field makes the query unsatisfiable rather than silently
                # matching everything or text-searching the value.
                logger.warning("Unknown search field(s), returning no results: %s", value)
                conditions.append("FALSE")
            elif property_name in (
                "name_contains",
                "name_excludes",
                "rules_text_contains",
                "rules_text_excludes",
            ):
                # Rules text matches either face (the back has its own text); name is identical
                # across faces, so it stays single-column.
                column = (
                    "c.name"
                    if property_name.startswith("name")
                    else "(c.rules_text || ' ' || COALESCE(back.rules_text, ''))"
                )
                op = "NOT ILIKE" if property_name.endswith("excludes") else "ILIKE"
                for needle in value:
                    conditions.append(f"{column} {op} %s ESCAPE '\\'")
                    params.append(f"%{_escape_like(needle)}%")
            elif property_name == "legality":
                formats, _statuses = value
                if isinstance(formats, str):
                    formats = [formats]
                if formats:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_legalities"
                        " WHERE format_name = ANY(%s))"
                    )
                    params.append(list(formats))
            elif property_name == "format_filters":
                # Each (operator, value) resolves the value against a format's name or short block
                # alias. Exact operators match that one format; inequalities compare every format's
                # legal_from to the reference format's, selecting one side of the arc timeline.
                for op, format_value in value:
                    if op in (":", "="):
                        conditions.append(
                            "c.card_id IN (SELECT cl.card_id FROM card_legalities cl"
                            " JOIN formats f ON f.name = cl.format_name"
                            " WHERE lower(f.name) = lower(%s) OR lower(f.block) = lower(%s))"
                        )
                        params.extend([format_value, format_value])
                    elif op in _RANGE_OPS:
                        conditions.append(
                            "c.card_id IN (SELECT cl.card_id FROM card_legalities cl"
                            " JOIN formats f ON f.name = cl.format_name"
                            f" WHERE f.legal_from {_RANGE_OPS[op]} (SELECT legal_from FROM formats"
                            " WHERE (lower(name) = lower(%s) OR lower(block) = lower(%s))"
                            " AND legal_from IS NOT NULL LIMIT 1))"
                        )
                        params.extend([format_value, format_value])
            elif property_name == "set_filters":
                # Each (operator, value) resolves the value against a set's full name or short code.
                # Exact operators match that set; inequalities compare every set's release_date to the
                # reference set's, selecting cards printed on one side of that release.
                for op, set_value in value:
                    if op in (":", "="):
                        conditions.append(
                            "c.card_id IN (SELECT p.card_id FROM prints p"
                            " JOIN l5r_sets s ON s.set_id = p.set_id"
                            " WHERE lower(s.set_name) = lower(%s) OR lower(s.code) = lower(%s))"
                        )
                        params.extend([set_value, set_value])
                    elif op in _RANGE_OPS:
                        conditions.append(
                            "c.card_id IN (SELECT p.card_id FROM prints p"
                            " JOIN l5r_sets s ON s.set_id = p.set_id"
                            f" WHERE s.release_date {_RANGE_OPS[op]} (SELECT release_date"
                            " FROM l5r_sets WHERE (lower(set_name) = lower(%s) OR lower(code) ="
                            " lower(%s)) AND release_date IS NOT NULL ORDER BY release_date LIMIT 1))"
                        )
                        params.extend([set_value, set_value])
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
                # Clan affiliation is materialised into card_clans for every card (the loader infers
                # it from keywords for senseis, holdings, and minor clans). `clan:all` is shorthand
                # for the "All Clans" senseis that any clan may lead.
                if value:
                    wanted = [c.lower() for c in value]
                    if "all" in wanted:
                        wanted.append("all clans")
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_clans WHERE lower(clan) = ANY(%s))"
                    )
                    params.append(wanted)
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
            elif property_name == "artist":
                for artist in value:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM prints"
                        " WHERE artist ILIKE %s ESCAPE '\\')"
                    )
                    params.append(f"%{_escape_like(artist)}%")
            elif property_name == "flavor":
                for flavor in value:
                    # A printing's special back (story scroll) keeps its prose in back_flavor.
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM prints"
                        " WHERE (flavor_text || ' ' || COALESCE(back_flavor, '')) ILIKE %s ESCAPE '\\')"
                    )
                    params.append(f"%{_escape_like(flavor)}%")
            elif property_name == "story":
                for story in value:
                    conditions.append("c.story ILIKE %s ESCAPE '\\'")
                    params.append(f"%{_escape_like(story)}%")
            elif property_name == "keywords":
                if value:
                    for keyword in value:
                        conditions.append(
                            "c.card_id IN (SELECT card_id FROM card_keywords"
                            " WHERE lower(keyword) = lower(%s))"
                        )
                        params.append(keyword)
            elif property_name == "keywords_or":
                # `is:a|b` — cards carrying any one of the keywords.
                if value:
                    conditions.append(
                        "c.card_id IN (SELECT card_id FROM card_keywords"
                        " WHERE lower(keyword) = ANY(%s))"
                    )
                    params.append([k.lower() for k in value])
            elif property_name in _NUMERIC_STATS:
                # A dash stat — one the card doesn't print — is stored as NULL. The whitelisted
                # column name is interpolation-safe (it is a key of _NUMERIC_STATS).
                if value == "isnull":
                    conditions.append(f"c.{property_name} IS NULL")
                elif value == "notnull":
                    conditions.append(f"c.{property_name} IS NOT NULL")
                elif isinstance(value, tuple) and len(value) == 2:
                    # Range matches consider the back face too, so a stat that differs per face
                    # (e.g. province_strength) matches when either side satisfies it.
                    min_val, max_val = value
                    range_predicates, range_params = [], []
                    for alias in ("c", "back"):
                        col = f"{alias}.{property_name}"
                        if min_val is not None and max_val is not None:
                            range_predicates.append(f"{col} >= %s AND {col} <= %s")
                            range_params.extend([min_val, max_val])
                        elif min_val is not None:
                            range_predicates.append(f"{col} >= %s")
                            range_params.append(min_val)
                        elif max_val is not None:
                            range_predicates.append(f"{col} <= %s")
                            range_params.append(max_val)
                    if range_predicates:
                        joined = " OR ".join(f"({predicate})" for predicate in range_predicates)
                        conditions.append(f"({joined})")
                        params.extend(range_params)
            elif value is not None:
                if property_name not in _ALLOWED_COLUMNS:
                    logger.warning(f"Ignoring unknown filter column: {property_name}")
                    continue
                conditions.append(f"c.{property_name} = %s")
                params.append(value)

    # Non-deck cards — proxies and everything filed under the "Other" deck (tokens, bio cards,
    # deckbackers, …) — are hidden by default. `include:tokens` brings the "Other" cards back
    # (proxies that are also tokens come with them); `include:all` shows everything.
    token = "EXISTS (SELECT 1 FROM card_decks d WHERE d.card_id = c.card_id AND d.deck = 'Other')"
    includes = filter_options.get("include", ()) if filter_options else ()
    if "all" not in includes:
        if "tokens" in includes:
            conditions.append(f"(NOT c.is_proxy OR {token})")
        else:
            conditions.append(f"(NOT c.is_proxy AND NOT {token})")

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
    select_sql, select_params = _card_select(_active_format(filter_options))
    sql = f"{select_sql} {where_clause} ORDER BY c.name"
    params = select_params + params

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


# An experience version can wear an epithet ("Bayushi Kachiko, Seven Thunder"), so sorting on the
# base name (before the first comma) keeps a character's versions together; experience then orders
# them (Inexperienced, base, Exp, Exp2, ...) and extended_title stabilises one level's set variants.
_NAME_SORT = "split_part(c.name, ',', 1)"
_NAME_TIEBREAK = f"{_NAME_SORT} ASC, c.experience ASC, c.extended_title ASC"


def _order_by_clause(sort: str, order: str) -> str:
    """Build a safe ``ORDER BY`` clause from a whitelisted sort key and direction.

    Numeric stats sort NULLs last (cards without the stat fall to the end in both directions); every
    sort then tiebreaks by base name, experience level, and extended_title for a stable, intuitive
    order. An unknown key falls back to name.
    """
    column = _SORT_COLUMNS.get(sort, "c.name")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"
    if column == "c.name":
        return f"ORDER BY {_NAME_SORT} {direction}, c.experience ASC, c.extended_title ASC"
    return f"ORDER BY {column} {direction} NULLS LAST, {_NAME_TIEBREAK}"


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
        Column to order by; one of name, force, chi, gold_cost, focus, personal_honor,
        honor_requirement, or province_strength. An unknown value falls back to name.
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
    select_sql, select_params = _card_select(_active_format(filter_options))

    count_sql = f"SELECT COUNT(*) AS n FROM cards c {_CROSS_FACE_JOIN} {where_clause}"
    data_sql = f"{select_sql} {where_clause} {_order_by_clause(sort, order)} LIMIT %s OFFSET %s"
    data_params = select_params + params + [limit, offset]

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
    sql = f"SELECT COUNT(*) AS n FROM cards c {_CROSS_FACE_JOIN} {where_clause}"

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
    conditions: list[str] = ["NOT c.is_back"]
    params: list = []

    if deck_filter:
        conditions.append(
            "EXISTS (SELECT 1 FROM card_decks d WHERE d.card_id = c.card_id AND d.deck = %s::deck_type)"
        )
        params.append(deck_filter)

    where_clause = "WHERE " + " AND ".join(conditions)

    # Draw the random ids from the bare cards table, then build the full record (lateral image join
    # and per-card aggregate subqueries) for only those rows. Sorting the whole select by RANDOM()
    # computes every card's aggregates before discarding all but ``count`` of them — a full-table
    # scan that times out at scale.
    select_sql, select_params = _card_select()
    picked = f"SELECT c.card_id FROM cards c {where_clause} ORDER BY RANDOM() LIMIT %s"
    sql = f"{select_sql} WHERE c.card_id IN ({picked}) ORDER BY RANDOM()"
    data_params = select_params + params + [count]

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, data_params)
            return cur.fetchall()
