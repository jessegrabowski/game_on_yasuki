import base64
import binascii
import os
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.websockets import WebSocket

WIP_PASSWORD_ENV = "WIP_PLAY_PASSWORD"

# The username is not a secret — the password is the whole gate. A fixed username keeps the
# browser's Basic-auth prompt to a single field that matters.
WIP_USERNAME = "yasuki"

_basic = HTTPBasic(auto_error=False)


def wip_password() -> str | None:
    """Return the shared WIP password, or None when unset or empty.

    Read at call time; a None result disables the WIP play routes (the gate fails closed).
    """
    return os.environ.get(WIP_PASSWORD_ENV) or None


def _credentials_ok(username: str, password: str, expected: str) -> bool:
    # Constant-time on both fields so neither the username nor the password leaks via timing.
    user_ok = secrets.compare_digest(username, WIP_USERNAME)
    pass_ok = secrets.compare_digest(password, expected)
    return user_ok and pass_ok


def require_wip_access(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Gate a route behind the shared WIP password (HTTP Basic Auth).

    Raise 404 when no password is configured (the surface looks absent) and 401 with a Basic
    challenge on missing or wrong credentials so the browser prompts.
    """
    expected = wip_password()
    if expected is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if credentials is None or not _credentials_ok(
        credentials.username, credentials.password, expected
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def websocket_access_ok(websocket: WebSocket) -> bool:
    """Return whether a WebSocket handshake carries valid WIP credentials.

    Browsers resend cached HTTP Basic credentials on same-origin requests, including the WebSocket
    upgrade, so authenticating to the page also covers the socket. Return False when the password is
    unset (surface disabled) or the ``Authorization`` header is missing or malformed.
    """
    expected = wip_password()
    if expected is None:
        return False
    header = websocket.headers.get("authorization")
    if not header or header[:6].lower() != "basic ":
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    return _credentials_ok(username, password, expected)
