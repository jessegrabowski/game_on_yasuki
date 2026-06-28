import hashlib
import hmac
import os
import secrets

_PEPPER_ENV = "YASUKI_EMAIL_HMAC_PEPPER"


def _pepper() -> bytes:
    pepper = os.environ.get(_PEPPER_ENV)
    if not pepper:
        raise RuntimeError(f"{_PEPPER_ENV} must be set to key the email blind index")
    return pepper.encode()


def email_blind_index(email: str) -> bytes:
    """Return the blind index stored for an email: ``HMAC-SHA256(normalized email, pepper)``.

    The email is lower-cased and stripped before hashing, so equality lookups (dup-account
    detection, ban-by-email) match regardless of the casing Google hands back. Raise RuntimeError
    when the pepper is unset.

    Parameters
    ----------
    email : str
        The address to index.

    Returns
    -------
    index : bytes
        The 32-byte HMAC-SHA256 digest.
    """
    return hmac.new(_pepper(), email.strip().lower().encode(), hashlib.sha256).digest()


def sub_blind_index(google_sub: str) -> bytes:
    """Return the banlist tombstone key for a Google identity: ``HMAC-SHA256("sub:" + sub, pepper)``.

    The subject identifier is opaque and stable, so it is hashed as-is apart from a ``sub:`` domain
    tag. The tag keeps this index's value space disjoint from the email index (which the email
    blind-index construction, frozen by stored data, leaves untagged), so the two banlist columns
    can never collide. Raise RuntimeError when the pepper is unset.

    Parameters
    ----------
    google_sub : str
        The Google subject identifier to index.

    Returns
    -------
    index : bytes
        The 32-byte HMAC-SHA256 digest.
    """
    return hmac.new(_pepper(), b"sub:" + google_sub.encode(), hashlib.sha256).digest()


def new_session_token() -> str:
    """Return a fresh high-entropy opaque session token for the cookie."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> bytes:
    """Return ``SHA-256(token)`` — the form stored server-side, so a DB leak can't mint sessions."""
    return hashlib.sha256(token.encode()).digest()
