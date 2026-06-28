import argparse
import logging
import sys
from collections.abc import Iterable
from importlib import resources

import psycopg
from psycopg.rows import tuple_row

from yasuki_core.accounts.db import accounts_connection_string
from yasuki_core.database import mask_dsn

logger = logging.getLogger(__name__)

_MIGRATIONS_PACKAGE = "yasuki_core.accounts.migrations"

# The ledger of applied migrations. Created on first run; tracks which migrations have been applied.
# Itself idempotent (IF NOT EXISTS).
_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def _migrations() -> list[tuple[str, str]]:
    """Return every migration as ``(version, sql)``, ordered by version.

    A migration's version is its filename without the ``.sql`` suffix (e.g. ``0001_initial``).
    Applying in sorted-filename order is what makes the sequence deterministic, so zero-pad new
    numbers (``0002_…``, ``0010_…``).
    """
    entries = resources.files(_MIGRATIONS_PACKAGE).iterdir()
    files = sorted((p for p in entries if p.name.endswith(".sql")), key=lambda p: p.name)
    return [(p.name[:-4], p.read_text(encoding="utf-8")) for p in files]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply every migration not yet recorded in ``schema_migrations``, in order, on ``conn``.

    Each migration runs in its own transaction and is recorded only on success, so a failure leaves
    the database at the last good version and a re-run resumes from there. Already-applied
    migrations are skipped, so this is safe to run on every deploy. ``migrate`` wraps this with a
    real connection; a caller may pass its own.

    Parameters
    ----------
    conn : psycopg.Connection
        An open connection, expected in autocommit mode; each migration is wrapped in its own
        explicit transaction.

    Returns
    -------
    applied : list of str
        The versions applied by this call, in order. Empty when the database is already current.
    """
    # tuple_row so the bookkeeping read works regardless of the connection's default row factory
    # (the production pool yields dict rows).
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(_TRACKING_DDL)
        cur.execute("SELECT version FROM schema_migrations")
        recorded = {row[0] for row in cur.fetchall()}

    applied = []
    for version, sql in _migrations():
        if version in recorded:
            continue
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        logger.info("Applied migration %s", version)
        applied.append(version)
    return applied


def migrate(dsn: str | None = None) -> list[str]:
    """Bring the accounts database up to the latest migration.

    Parameters
    ----------
    dsn : str, optional
        The accounts-database DSN to apply against. Default the value from
        ``accounts_connection_string()``.

    Returns
    -------
    applied : list of str
        The versions applied by this call (empty when already current).
    """
    dsn = dsn or accounts_connection_string()
    logger.info("Applying accounts migrations to %s", mask_dsn(dsn))
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        applied = apply_migrations(conn)
    if applied:
        logger.info("Applied %d migration(s); accounts schema now current", len(applied))
    else:
        logger.info("Accounts schema already current")
    return applied


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending accounts-database migrations (ordered; applies only what is new)"
    )
    parser.add_argument(
        "--dsn",
        default=None,
        help="Accounts DSN; defaults to $YASUKI_ACCOUNTS_DATABASE_URL",
    )
    args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        migrate(args.dsn)
    except psycopg.OperationalError as exc:
        logger.error("Accounts DB connection failed: %s", exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
