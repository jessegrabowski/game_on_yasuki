import hashlib

import psycopg
import pytest

from yasuki_core.accounts.db import accounts_connection_string
from yasuki_core.accounts.migrate import _migrations, apply_migrations
from yasuki_core.database import get_connection_string

# The DDL and queries are identical whether they run in the dedicated accounts database or in a
# throwaway schema of the card database; only the deploy-time database boundary differs (asserted
# structurally by test_dsn_is_separate_from_card_db, which needs no server). So the round-trip tests
# run against whatever Postgres is available, isolated in their own schema, instead of requiring a
# separately provisioned accounts DB that a fresh clone / CI would lack.
_TEST_SCHEMA = "accounts_schema_test"


def _db_available() -> bool:
    try:
        psycopg.connect(get_connection_string(), connect_timeout=5).close()
        return True
    except psycopg.OperationalError:
        return False


def _digest(value: str) -> bytes:
    """A stand-in for the production pepper'd HMAC — the schema only needs unique bytes."""
    return hashlib.sha256(value.encode()).digest()


@pytest.fixture
def conn():
    if not _db_available():
        pytest.skip("PostgreSQL not available")
    connection = psycopg.connect(get_connection_string(), autocommit=True)
    with connection.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {_TEST_SCHEMA}")
        cur.execute(f"SET search_path TO {_TEST_SCHEMA}")
    apply_migrations(connection)
    try:
        yield connection
    finally:
        with connection.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE")
        connection.close()


def _new_user(cur, sub="sub-1", email="ada@example.com", name="Ada") -> int:
    cur.execute(
        "INSERT INTO users (google_sub, email_hmac, email_verified, display_name) "
        "VALUES (%s, %s, true, %s) RETURNING id",
        (sub, _digest(email), name),
    )
    return cur.fetchone()[0]


def test_schema_creates_all_tables(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (_TEST_SCHEMA,),
        )
        tables = {row[0] for row in cur.fetchall()}
    assert {"users", "sessions", "decks", "deck_cards", "banlist"} <= tables


def test_rerunning_migrations_is_a_noop(conn):
    # The fixture already applied everything, so a second run applies and records nothing.
    assert apply_migrations(conn) == []
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        assert [row[0] for row in cur.fetchall()] == ["0001_initial"]


def test_user_deck_round_trip(conn):
    with conn.cursor() as cur:
        user_id = _new_user(cur)
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES (%s, %s, %s) RETURNING id",
            ("crab-beats", user_id, "Crab Beats"),
        )
        deck_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
            "VALUES (%s, %s, %s, 'dynasty', %s)",
            (deck_id, "hida_kisada", "Hida Kisada", 1),
        )
        cur.execute("SELECT card_name, quantity FROM deck_cards WHERE deck_id = %s", (deck_id,))
        assert cur.fetchone() == ("Hida Kisada", 1)


def test_deleting_user_cascades_decks_and_sessions(conn):
    with conn.cursor() as cur:
        user_id = _new_user(cur, sub="sub-cascade", email="kenji@example.com", name="Kenji")
        cur.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) "
            "VALUES (%s, %s, now() + interval '1 day')",
            (_digest("token"), user_id),
        )
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES ('d-cascade', %s, 'D') RETURNING id",
            (user_id,),
        )
        deck_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
            "VALUES (%s, 'c', 'C', 'fate', 1)",
            (deck_id,),
        )

        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))

        for table, column in (("sessions", "user_id"), ("decks", "owner_id")):
            cur.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (user_id,))
            assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM deck_cards WHERE deck_id = %s", (deck_id,))
        assert cur.fetchone()[0] == 0


def test_email_hmac_is_unique(conn):
    with conn.cursor() as cur:
        _new_user(cur, sub="sub-a", email="dup@example.com", name="A")
        with pytest.raises(psycopg.errors.UniqueViolation):
            _new_user(cur, sub="sub-b", email="dup@example.com", name="B")


def test_deck_cards_collapse_duplicates_but_keep_art_variants(conn):
    with conn.cursor() as cur:
        user_id = _new_user(cur, sub="sub-variant", email="variant@example.com", name="V")
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES ('d-variant', %s, 'D') RETURNING id",
            (user_id,),
        )
        deck_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
            "VALUES (%s, 'kuni', 'Kuni', 'dynasty', 2)",
            (deck_id,),
        )
        # Same card, side, and (null) art variant is the same row — must collide.
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
                "VALUES (%s, 'kuni', 'Kuni', 'dynasty', 1)",
                (deck_id,),
            )
        # An art-swapped copy of the same card is a distinct visual variant — must be allowed.
        cur.execute(
            "INSERT INTO deck_cards "
            "(deck_id, card_id, card_name, side, quantity, art_donor_card_id, art_donor_set) "
            "VALUES (%s, 'kuni', 'Kuni', 'dynasty', 1, 'other_kuni', 'GEM')",
            (deck_id,),
        )
        cur.execute("SELECT count(*) FROM deck_cards WHERE deck_id = %s", (deck_id,))
        assert cur.fetchone()[0] == 2


def test_quantity_must_be_positive(conn):
    with conn.cursor() as cur:
        user_id = _new_user(cur, sub="sub-qty", email="qty@example.com", name="Q")
        cur.execute(
            "INSERT INTO decks (slug, owner_id, name) VALUES ('d-qty', %s, 'D') RETURNING id",
            (user_id,),
        )
        deck_id = cur.fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO deck_cards (deck_id, card_id, card_name, side, quantity) "
                "VALUES (%s, 'x', 'X', 'fate', 0)",
                (deck_id,),
            )


def test_dsn_is_separate_from_card_db(monkeypatch):
    # The physical-isolation guarantee: with no env overrides the accounts DSN targets a different
    # database than the card DSN, so the card installer's DROP SCHEMA can never reach user data.
    for var in ("YASUKI_ACCOUNTS_DATABASE_URL", "YASUKI_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert accounts_connection_string() != get_connection_string()
    assert "yasuki_accounts" in accounts_connection_string()


def test_initial_migration_is_discovered():
    # No DB needed: the baseline must ship and be the first migration the runner sees.
    assert _migrations()[0][0] == "0001_initial"


def test_runner_applies_only_pending_in_order_including_alters(conn, monkeypatch):
    create = ("9001_create", "CREATE TABLE evolving (id int PRIMARY KEY)")
    alter = ("9002_alter", "ALTER TABLE evolving ADD COLUMN added text")

    def column_exists() -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'evolving' AND column_name = 'added'",
                (_TEST_SCHEMA,),
            )
            return cur.fetchone() is not None

    monkeypatch.setattr("yasuki_core.accounts.migrate._migrations", lambda: [create])
    assert apply_migrations(conn) == ["9001_create"]
    assert not column_exists()

    # Exposing the ALTER must apply only it — not re-run the recorded create — and evolve the live
    # table, the capability numbered migrations exist to provide.
    monkeypatch.setattr("yasuki_core.accounts.migrate._migrations", lambda: [create, alter])
    assert apply_migrations(conn) == ["9002_alter"]
    assert column_exists()
    assert apply_migrations(conn) == []


def test_runner_stops_at_a_failing_migration_and_keeps_the_last_good(conn, monkeypatch):
    good = ("9001_good", "CREATE TABLE good_one (id int)")
    bad = ("9002_bad", "CREATE TABLE bad_one (this is not valid sql)")

    monkeypatch.setattr("yasuki_core.accounts.migrate._migrations", lambda: [good, bad])
    with pytest.raises(psycopg.errors.SyntaxError):
        apply_migrations(conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT version FROM schema_migrations WHERE version LIKE '9%%' ORDER BY version"
        )
        assert [row[0] for row in cur.fetchall()] == ["9001_good"]
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name IN ('good_one', 'bad_one')",
            (_TEST_SCHEMA,),
        )
        assert {row[0] for row in cur.fetchall()} == {"good_one"}
