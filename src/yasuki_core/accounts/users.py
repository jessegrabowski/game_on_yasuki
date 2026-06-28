import psycopg

from yasuki_core.accounts.crypto import email_blind_index

# Returned on every user lookup — the non-sensitive identity the web layer needs to seat a player
# and enforce a ban. Deliberately excludes the email blind index.
_USER_COLUMNS = "id, google_sub, display_name, avatar_url, is_banned"


def upsert_user(
    conn: psycopg.Connection,
    google_sub: str,
    email: str,
    email_verified: bool,
    display_name: str,
    avatar_url: str | None = None,
) -> dict:
    """Insert the user for a Google ``sub``, or refresh the existing one, and return it.

    A returning user's ``display_name`` is left untouched — it is theirs to change and must not be
    clobbered by Google's current name — while the email index, verified flag, avatar, and login
    timestamp refresh each sign-in. ``email`` is stored only as its blind index, never in the clear.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    google_sub : str
        The Google subject identifier; the stable identity key.
    email : str
        The address from the verified id_token, stored only as a blind index.
    email_verified : bool
        Google's ``email_verified`` claim.
    display_name : str
        The name to seed a new account with; ignored for an existing one.
    avatar_url : str, optional
        Google's ``picture`` URL. Default None.

    Returns
    -------
    user : dict
        The row, with keys ``id``, ``google_sub``, ``display_name``, ``avatar_url``, ``is_banned``.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO users (google_sub, email_hmac, email_verified, display_name, avatar_url,
                               last_login_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (google_sub) DO UPDATE SET
                email_hmac = EXCLUDED.email_hmac,
                email_verified = EXCLUDED.email_verified,
                avatar_url = EXCLUDED.avatar_url,
                last_login_at = now(),
                updated_at = now()
            RETURNING {_USER_COLUMNS}
            """,
            (google_sub, email_blind_index(email), email_verified, display_name, avatar_url),
        )
        return cur.fetchone()


def get_user(conn: psycopg.Connection, user_id: int) -> dict | None:
    """Return the user with ``user_id``, or None if absent."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()
