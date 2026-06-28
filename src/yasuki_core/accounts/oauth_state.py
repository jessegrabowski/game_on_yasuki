from datetime import timedelta

import psycopg


def stash_login(
    conn: psycopg.Connection,
    state: str,
    nonce: str,
    code_verifier: str,
    redirect_to: str | None = None,
) -> None:
    """Record the in-flight OAuth state for a login, to be consumed at the callback.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    state : str
        The random CSRF state Google will echo back.
    nonce : str
        The OIDC nonce bound into the requested id_token.
    code_verifier : str
        The PKCE verifier whose challenge was sent to Google.
    redirect_to : str, optional
        A same-site path to land on after login. Default None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO oauth_logins (state, nonce, code_verifier, redirect_to) "
            "VALUES (%s, %s, %s, %s)",
            (state, nonce, code_verifier, redirect_to),
        )


def pop_login(conn: psycopg.Connection, state: str, max_age: timedelta) -> dict | None:
    """Consume the login state for ``state``, or None if absent or older than ``max_age``.

    The row is deleted as it is read, so a state is single-use — a replayed or forged callback finds
    nothing.

    Parameters
    ----------
    conn : psycopg.Connection
        An open accounts-database connection.
    state : str
        The CSRF state returned on the callback.
    max_age : datetime.timedelta
        Reject a login older than this, guarding against stale or hoarded states.

    Returns
    -------
    login : dict or None
        Keys ``nonce``, ``code_verifier``, ``redirect_to`` for a fresh state, else None.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM oauth_logins WHERE state = %s AND created_at > now() - %s "
            "RETURNING nonce, code_verifier, redirect_to",
            (state, max_age),
        )
        return cur.fetchone()


def purge_stale_logins(conn: psycopg.Connection, max_age: timedelta) -> int:
    """Delete abandoned login rows older than ``max_age``; return how many were removed."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM oauth_logins WHERE created_at <= now() - %s", (max_age,))
        return cur.rowcount
