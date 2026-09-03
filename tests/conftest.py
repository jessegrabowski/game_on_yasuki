import os

import psycopg
import pytest
from psycopg.rows import dict_row

from yasuki_core.accounts.migrate import apply_migrations
from yasuki_core.database import get_connection_string

# The DDL and queries are identical whether they run in the dedicated accounts database or in a
# throwaway schema of the card database; only the deploy-time database boundary differs. So tests
# run against whatever Postgres is available, isolated in their own schema, instead of requiring a
# separately provisioned accounts DB that a fresh clone / CI would lack.
ACCOUNTS_TEST_SCHEMA = "accounts_test"


def _schema_name() -> str:
    """The throwaway schema this process owns.

    The fixture drops the schema on the way in and on the way out, so workers running in parallel
    would demolish each other's tables mid-test if they shared one name. ``PYTEST_XDIST_WORKER`` is
    unset outside a parallel run, which leaves a single serial schema.
    """
    return f"{ACCOUNTS_TEST_SCHEMA}_{os.environ.get('PYTEST_XDIST_WORKER', 'main')}"


def _db_available() -> bool:
    try:
        psycopg.connect(get_connection_string(), connect_timeout=5).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def accounts_conn():
    """A dict-row connection scoped to a throwaway schema with all accounts migrations applied.

    Uses ``dict_row`` to match the production pool, so repository code behaves identically here.
    """
    if not _db_available():
        pytest.skip("PostgreSQL not available")
    schema = _schema_name()
    conn = psycopg.connect(get_connection_string(), autocommit=True, row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(f"SET search_path TO {schema}")
    apply_migrations(conn)
    try:
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        conn.close()
