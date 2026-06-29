import psycopg

from yasuki_core.accounts.crypto import email_blind_index, sub_blind_index


def tombstone(
    conn: psycopg.Connection, google_sub: str, email_hmac: bytes, reason: str | None = None
) -> None:
    """Record a banned identity's pepper'd sub and email hashes so it cannot re-register.

    The tombstone outlives the user row (it survives GDPR erasure), holding only hashes — no raw
    PII. Re-banning the same identity refreshes the email hash, reason, and timestamp.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    google_sub : str
        The banned account's Google subject identifier; stored only as its blind index.
    email_hmac : bytes
        The account's already-computed email blind index, as held on the user row.
    reason : str, optional
        A free-text ban reason. Default None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO banlist (sub_hmac, email_hmac, reason) VALUES (%s, %s, %s) "
            "ON CONFLICT (sub_hmac) DO UPDATE SET "
            "email_hmac = EXCLUDED.email_hmac, reason = EXCLUDED.reason, banned_at = now()",
            (sub_blind_index(google_sub), email_hmac, reason),
        )


def remove(conn: psycopg.Connection, google_sub: str) -> None:
    """Drop a tombstone by its Google sub, so the identity may sign in again (unban)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM banlist WHERE sub_hmac = %s", (sub_blind_index(google_sub),))


def is_banned(conn: psycopg.Connection, google_sub: str, email: str) -> bool:
    """Whether an incoming Google identity matches a banlist tombstone, by sub or by email.

    Checked at signup so a banned person cannot return under a fresh account row — neither by
    re-using the same Google account (sub match) nor a new one on the same address (email match).

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    google_sub : str
        The subject identifier from the verified id_token.
    email : str
        The address from the verified id_token.

    Returns
    -------
    banned : bool
        True if either hash is tombstoned.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM banlist WHERE sub_hmac = %s OR email_hmac = %s LIMIT 1",
            (sub_blind_index(google_sub), email_blind_index(email)),
        )
        return cur.fetchone() is not None
