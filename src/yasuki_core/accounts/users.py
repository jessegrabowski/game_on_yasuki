import psycopg
from psycopg.types.json import Jsonb

from yasuki_core.accounts import banlist, sessions
from yasuki_core.accounts.crypto import email_blind_index

# Returned on every user lookup — the non-sensitive identity the web layer needs to seat a player
# and enforce a ban. Deliberately excludes the email blind index.
_USER_COLUMNS = "id, google_sub, display_name, role, is_approved, is_banned, avatar"


def upsert_user(
    conn: psycopg.Connection,
    google_sub: str,
    email: str,
    email_verified: bool,
    display_name: str | None,
) -> dict:
    """Insert the user for a Google ``sub``, or refresh the existing one, and return it.

    A returning user's ``display_name`` is left untouched — it is theirs to change and must not be
    clobbered by Google's current name — while the email index, verified flag, and login timestamp
    refresh each sign-in. ``email`` is stored only as its blind index, never in the clear. A new
    account passes ``None`` and is nameless until it picks a display name during onboarding.

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
    display_name : str or None
        The name to seed a new account with, or None to leave it nameless until onboarding; ignored
        for an existing one.

    Returns
    -------
    user : dict
        The row, with keys ``id``, ``google_sub``, ``display_name``, ``role``, ``is_banned``,
        ``avatar``, plus ``created`` — True only on first sign-in, so the caller can onboard.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO users (google_sub, email_hmac, email_verified, display_name, last_login_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (google_sub) DO UPDATE SET
                email_hmac = EXCLUDED.email_hmac,
                email_verified = EXCLUDED.email_verified,
                last_login_at = now(),
                updated_at = now()
            RETURNING {_USER_COLUMNS}, (xmax = 0) AS created
            """,
            (google_sub, email_blind_index(email), email_verified, display_name),
        )
        return cur.fetchone()


def set_display_name(conn: psycopg.Connection, user_id: int, display_name: str) -> dict | None:
    """Update a user's display name, returning the refreshed row, or None if no such user."""
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE users SET display_name = %s, updated_at = now() WHERE id = %s "
            f"RETURNING {_USER_COLUMNS}",
            (display_name, user_id),
        )
        return cur.fetchone()


def set_avatar(conn: psycopg.Connection, user_id: int, avatar: dict | None) -> dict | None:
    """Set (or clear, with None) a user's avatar spec, returning the refreshed row, or None if absent.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    user_id : int
        The user to update.
    avatar : dict or None
        The avatar spec ``{card_id, image_path, crop}`` to store as JSON, or None to clear it.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE users SET avatar = %s, updated_at = now() WHERE id = %s RETURNING {_USER_COLUMNS}",
            (Jsonb(avatar) if avatar is not None else None, user_id),
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


def list_users(conn: psycopg.Connection) -> list[dict]:
    """Return every account for the admin dashboard, newest first.

    Carries only the non-sensitive fields an admin needs to triage and ban — never the email blind
    index. ``last_seen`` is the most recent of the last login and any live session's activity, so an
    active user reads as recent even between logins. Each row has keys ``id``, ``display_name``,
    ``role``, ``is_approved``, ``is_banned``, ``created_at``, and ``last_seen``.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT u.id, u.display_name, u.role, u.is_approved, u.is_banned, u.created_at, "
            "GREATEST(u.last_login_at, MAX(s.last_seen_at)) AS last_seen "
            "FROM users u LEFT JOIN sessions s ON s.user_id = u.id "
            "GROUP BY u.id ORDER BY u.created_at DESC"
        )
        return cur.fetchall()


def set_role(conn: psycopg.Connection, user_id: int, role: str) -> bool:
    """Set a user's role, returning whether a user was there to update."""
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET role = %s, updated_at = now() WHERE id = %s", (role, user_id))
        return cur.rowcount > 0


def set_approved(conn: psycopg.Connection, user_id: int, approved: bool) -> bool:
    """Set a user's approval flag, returning whether a user was there to update."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_approved = %s, updated_at = now() WHERE id = %s",
            (approved, user_id),
        )
        return cur.rowcount > 0


def unban_user(conn: psycopg.Connection, user_id: int) -> bool:
    """Lift a ban: clear the row's flag and reason and drop the identity's tombstone.

    The inverse of :func:`ban_user`. Removing the tombstone lets the identity sign in again. Return
    whether a user was there to unban.
    """
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET is_banned = false, banned_at = NULL, ban_reason = NULL "
            "WHERE id = %s RETURNING google_sub",
            (user_id,),
        )
        row = cur.fetchone()
        if row is None:
            return False
        banlist.remove(conn, row["google_sub"])
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
