from functools import cache

import psycopg
import pytest

from yasuki_core.database import get_connection_string


@cache
def _db_available() -> bool:
    try:
        psycopg.connect(get_connection_string()).close()
        return True
    except psycopg.OperationalError:
        return False


# Cards come from Postgres, so anything that resolves a real decklist runs in the Docker integration
# job and skips in the bare unit-test jobs.
requires_db = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")
