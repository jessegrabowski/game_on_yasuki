import psycopg

from yasuki_core.accounts import banlist, sessions
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


def ban_user(conn: psycopg.Connection, user_id: int, reason: str | None = None) -> bool:
    """Ban a live user: flag the row, revoke every session, and tombstone the identity.

    The tombstone means the ban survives even if the user later deletes their account. Return
    whether a user was there to ban.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    user_id : int
        The user to ban.
    reason : str, optional
        A free-text ban reason, kept on the row and the tombstone. Default None.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_banned = true, banned_at = now(), ban_reason = %s "
            "WHERE id = %s RETURNING google_sub, email_hmac",
            (reason, user_id),
        )
        row = cur.fetchone()
        if row is None:
            return False
        banlist.tombstone(conn, row["google_sub"], row["email_hmac"], reason)
        sessions.delete_user_sessions(conn, user_id)
    return True


def delete_account(conn: psycopg.Connection, user_id: int) -> bool:
    """Erase a user (GDPR right to erasure), cascading their sessions and decks.

    A banned user's pepper'd sub/email tombstone is retained first, so erasure cannot reopen the
    door to a banned identity; a user in good standing leaves nothing behind. The row's deletion
    cascades to sessions, decks, and deck cards via their foreign keys. Return whether a user was
    there to delete.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    user_id : int
        The user to erase.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "SELECT google_sub, email_hmac, is_banned, ban_reason FROM users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        if row["is_banned"]:
            banlist.tombstone(conn, row["google_sub"], row["email_hmac"], row["ban_reason"])
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
    return True
