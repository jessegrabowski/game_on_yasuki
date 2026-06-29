from datetime import timedelta

import psycopg

from yasuki_core.accounts.crypto import hash_session_token, new_session_token


def create_session(conn: psycopg.Connection, user_id: int, ttl: timedelta) -> str:
    """Create a session for ``user_id`` and return its raw token (stored only as a hash).

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    user_id : int
        The owner of the session.
    ttl : datetime.timedelta
        How long the session stays valid from now.

    Returns
    -------
    token : str
        The raw token to set in the cookie; never persisted.
    """
    token = new_session_token()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, now() + %s)",
            (hash_session_token(token), user_id, ttl),
        )
    return token


def resolve_session(conn: psycopg.Connection, token: str) -> dict | None:
    """Return the user behind a live session token, or None.

    A session resolves only when it exists, has not expired, and its user is not banned; touch
    ``last_seen_at`` as a side effect. A banned, expired, or unknown token yields None, so the
    caller treats the request as anonymous.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    token : str
        The raw token from the cookie.

    Returns
    -------
    user : dict or None
        The user row (same shape as ``users.get_user``) for a valid session, else None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sessions SET last_seen_at = now() "
            "WHERE token_hash = %s AND expires_at > now() RETURNING user_id",
            (hash_session_token(token),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "SELECT id, google_sub, display_name, avatar_url, is_banned, avatar "
            "FROM users WHERE id = %s",
            (row["user_id"],),
        )
        user = cur.fetchone()
    if user is None or user["is_banned"]:
        return None
    return user


def delete_session(conn: psycopg.Connection, token: str) -> None:
    """Revoke a single session (logout)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE token_hash = %s", (hash_session_token(token),))


def delete_user_sessions(conn: psycopg.Connection, user_id: int) -> None:
    """Revoke every session a user holds (logout-everywhere, or on ban)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
