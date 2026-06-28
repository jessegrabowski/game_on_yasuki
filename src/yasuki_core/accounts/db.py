import logging
import os
from collections.abc import Generator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from yasuki_core.database import apply_sslmode

logger = logging.getLogger(__name__)

# A pool distinct from the card DB's (database.py): user data lives in a physically separate
# Postgres so the card installer's DROP SCHEMA can never reach it. Lighter traffic than card reads
# (login, save deck), so it runs leaner.
_pool: ConnectionPool | None = None


def accounts_connection_string() -> str:
    """DSN for the accounts database — a separate Postgres from the card DB.

    Read ``YASUKI_ACCOUNTS_DATABASE_URL``; fall back to a local ``yasuki_accounts`` database so
    development needs only a second database on the same server, not a second server. Apply the same
    TLS treatment as the card pool (verify-full / require on public hosts).

    Returns
    -------
    dsn : str
        The accounts-database connection string.
    """
    dsn = os.environ.get("YASUKI_ACCOUNTS_DATABASE_URL", "postgresql://localhost/yasuki_accounts")
    return apply_sslmode(dsn)


def init_accounts_pool(min_size: int = 1, max_size: int = 10) -> None:
    """Open the module-level accounts connection pool. A no-op if it is already open.

    Parameters
    ----------
    min_size : int
        Minimum number of idle connections kept in the pool. Default 1.
    max_size : int
        Maximum number of connections the pool will open. Default 10.
    """
    global _pool
    if _pool is not None:
        return
    _pool = ConnectionPool(
        conninfo=accounts_connection_string(),
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
    logger.info("Accounts DB pool initialized (min=%d, max=%d)", min_size, max_size)


def close_accounts_pool() -> None:
    """Close the accounts connection pool and release all connections."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
        logger.info("Accounts DB pool closed")


@contextmanager
def get_accounts_connection() -> Generator[psycopg.Connection, None, None]:
    """Context manager for accounts-database connections from the pool.

    Open the pool on first use if it has not been opened yet.

    Yields
    ------
    conn : psycopg.Connection
        Connection with autocommit enabled and a dict row factory.
    """
    if _pool is None:
        init_accounts_pool()
    with _pool.connection() as conn:
        yield conn
