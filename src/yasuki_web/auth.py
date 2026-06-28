import asyncio
import base64
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse
from starlette.websockets import WebSocket

from yasuki_core.accounts import oauth_state, sessions, users
from yasuki_core.accounts.db import get_accounts_connection

logger = logging.getLogger(__name__)

router = APIRouter()

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
# Google mints id_tokens under either spelling; accept both rather than guess.
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

SESSION_COOKIE = "yasuki_session"
SESSION_TTL = timedelta(days=30)
# A login must reach the callback within this window; stale OAuth state is rejected and swept.
LOGIN_STATE_TTL = timedelta(minutes=10)
DEFAULT_LANDING = "/top-secret.html"

# Tolerance for clock skew between us and Google when checking the id_token's expiry/issued-at.
CLOCK_SKEW_LEEWAY_S = 10
# Cap on the blocking call to Google's token endpoint.
TOKEN_EXCHANGE_TIMEOUT_S = 10


@dataclass(frozen=True)
class _OAuthConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


def _config() -> _OAuthConfig | None:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI")
    if not (client_id and client_secret and redirect_uri):
        return None
    return _OAuthConfig(client_id, client_secret, redirect_uri)


def _require_config() -> _OAuthConfig:
    config = _config()
    if config is None:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    return config


def _is_secure(request: Request) -> bool:
    return request.headers.get("x-forwarded-proto", request.url.scheme) == "https"


def _safe_next(raw: str | None) -> str | None:
    """Return ``raw`` only if it is a same-site absolute path, guarding against open redirects."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return None


def _pkce_pair() -> tuple[str, str]:
    """Return a ``(verifier, S256 challenge)`` PKCE pair."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


_jwks_client: jwt.PyJWKClient | None = None


def _signing_key(id_token: str):
    """Return the Google public key that signed ``id_token`` (cached JWKS client)."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(GOOGLE_JWKS_URI)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def _verify_id_token(id_token: str, nonce: str, client_id: str) -> dict:
    """Verify a Google id_token's signature and claims, returning its payload.

    Check the RS256 signature against Google's JWKS, the audience, expiry, issuer, and that the
    nonce matches the one bound at ``/auth/login``. Raise ``jwt.InvalidTokenError`` (or a subclass)
    on any failure.
    """
    claims = jwt.decode(
        id_token,
        _signing_key(id_token),
        algorithms=["RS256"],
        audience=client_id,
        leeway=CLOCK_SKEW_LEEWAY_S,
    )
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise jwt.InvalidIssuerError("unexpected issuer")
    if claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("nonce mismatch")
    return claims


def _exchange_code(code: str, code_verifier: str, config: _OAuthConfig) -> str:
    """Exchange an authorization code for Google's id_token, completing the PKCE handshake."""
    response = httpx.post(
        GOOGLE_TOKEN_URI,
        data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=TOKEN_EXCHANGE_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()["id_token"]


def _resolve_user(token: str) -> dict | None:
    with get_accounts_connection() as conn:
        return sessions.resolve_session(conn, token)


def _stash_login(state: str, nonce: str, verifier: str, redirect_to: str | None) -> None:
    with get_accounts_connection() as conn:
        oauth_state.stash_login(conn, state, nonce, verifier, redirect_to)


def _pop_login(state: str) -> dict | None:
    with get_accounts_connection() as conn:
        return oauth_state.pop_login(conn, state, LOGIN_STATE_TTL)


def _complete_login(claims: dict) -> str | None:
    """Upsert the authenticated user and return a new session token, or None if they are banned."""
    with get_accounts_connection() as conn:
        user = users.upsert_user(
            conn,
            claims["sub"],
            claims["email"],
            email_verified=bool(claims.get("email_verified")),
            display_name=claims.get("name") or claims["email"],
            avatar_url=claims.get("picture"),
        )
        if user["is_banned"]:
            return None
        return sessions.create_session(conn, user["id"], SESSION_TTL)


def _logout(token: str) -> None:
    with get_accounts_connection() as conn:
        sessions.delete_session(conn, token)


async def current_user_optional(request: Request) -> dict | None:
    """The user behind the session cookie, or None — the additive dependency for public routes."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await asyncio.to_thread(_resolve_user, token)


async def current_user(request: Request) -> dict:
    """The authenticated user, or 401 — the gate for login-required routes."""
    user = await current_user_optional(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def user_for_websocket(websocket: WebSocket) -> dict | None:
    """The user behind the session cookie on a WebSocket handshake, or None.

    Browsers send the session cookie on the upgrade request, so the same cookie that authenticates
    HTTP routes also identifies the socket. The play surface is login-required, so a None result is
    the signal to close the handshake.
    """
    token = websocket.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await asyncio.to_thread(_resolve_user, token)


@router.get("/auth/login")
async def login(request: Request):
    config = _require_config()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    redirect_to = _safe_next(request.query_params.get("next"))
    await asyncio.to_thread(_stash_login, state, nonce, verifier, redirect_to)

    params = urlencode(
        {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return RedirectResponse(f"{GOOGLE_AUTH_URI}?{params}", status_code=302)


@router.get("/auth/callback")
async def callback(request: Request):
    config = _require_config()
    params = request.query_params
    if params.get("error"):
        raise HTTPException(status_code=400, detail="Authorization was denied")
    code, state = params.get("code"), params.get("state")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    login_state = await asyncio.to_thread(_pop_login, state)
    if login_state is None:
        raise HTTPException(status_code=400, detail="Invalid or expired login state")

    try:
        id_token = await asyncio.to_thread(
            _exchange_code, code, login_state["code_verifier"], config
        )
        claims = await asyncio.to_thread(
            _verify_id_token, id_token, login_state["nonce"], config.client_id
        )
    except (httpx.HTTPError, KeyError, jwt.InvalidTokenError):
        logger.warning("OAuth callback verification failed", exc_info=True)
        raise HTTPException(status_code=400, detail="Could not verify Google sign-in")

    if not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Google email is required")

    token = await asyncio.to_thread(_complete_login, claims)
    if token is None:
        raise HTTPException(status_code=403, detail="This account is banned")

    landing = _safe_next(login_state.get("redirect_to")) or DEFAULT_LANDING
    response = RedirectResponse(landing, status_code=302)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=_is_secure(request),
        samesite="lax",
        path="/",
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await asyncio.to_thread(_logout, token)
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=_is_secure(request), samesite="lax"
    )
    return response


@router.get("/api/me")
async def me(user: dict | None = Depends(current_user_optional)):
    if user is None:
        return {"user": None}
    return {
        "user": {
            "id": user["id"],
            "display_name": user["display_name"],
            "avatar_url": user["avatar_url"],
        }
    }
