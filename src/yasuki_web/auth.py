import asyncio
import base64
import hashlib
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from starlette.responses import JSONResponse, RedirectResponse
from starlette.websockets import WebSocket

from yasuki_web.rate_limit import limiter

from yasuki_core.accounts import banlist, oauth_state, roles, sessions, users
from yasuki_core.accounts.db import get_accounts_connection
from yasuki_core.database import get_card_by_id
from yasuki_web.notifications import notify_new_signup

logger = logging.getLogger(__name__)

router = APIRouter()

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
# Google mints id_tokens under either spelling; accept both rather than guess.
GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})

SESSION_COOKIE = "yasuki_session"
SESSION_TTL = timedelta(days=30)
# Local-only sign-in shortcut, gated by this env var and refused in production (see _dev_login_enabled).
DEV_LOGIN_ENV = "YASUKI_DEV_LOGIN"
# A login must reach the callback within this window; stale OAuth state is rejected and swept.
LOGIN_STATE_TTL = timedelta(minutes=10)
DEFAULT_LANDING = "/play"

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


def _complete_login(claims: dict) -> tuple[str, dict] | None:
    """Upsert the authenticated user and return ``(session token, user)``, or None if banned.

    A new account is created nameless — it picks a display name during onboarding, so the Google
    profile name never even touches the row. A banlist tombstone is checked before any row is
    created, so a banned identity cannot slip back in by having deleted its account; the live
    ``is_banned`` flag is the second guard. The returned user carries ``created`` and
    ``is_approved`` so the caller can onboard a new or still-pending account.
    """
    with get_accounts_connection() as conn:
        if banlist.is_banned(conn, claims["sub"], claims["email"]):
            return None
        user = users.upsert_user(
            conn,
            claims["sub"],
            claims["email"],
            email_verified=bool(claims.get("email_verified")),
            display_name=None,
        )
        if user["is_banned"]:
            return None
        return sessions.create_session(conn, user["id"], SESSION_TTL), user


def _logout(token: str) -> None:
    with get_accounts_connection() as conn:
        sessions.delete_session(conn, token)


def _delete_account(user_id: int) -> None:
    with get_accounts_connection() as conn:
        users.delete_account(conn, user_id)


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


async def require_admin(user: dict = Depends(current_user)) -> dict:
    """The authenticated user if an admin, else 403 — the gate for the admin dashboard."""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def require_approved(user: dict = Depends(current_user)) -> dict:
    """The user if their account is ready for the product (named and approved), else 403.

    Gates play and saving decks. A new account must finish onboarding (pick a display name) and then
    be approved by an admin; profile self-service stays open so a pending user can do both.
    """
    if not user.get("display_name"):
        raise HTTPException(status_code=403, detail="Finish setting up your account first")
    if not user.get("is_approved"):
        raise HTTPException(status_code=403, detail="Your account is awaiting admin approval")
    return user


async def user_for_websocket(websocket: WebSocket) -> dict | None:
    """The user behind the session cookie on a WebSocket handshake, or None.

    Browsers send the session cookie on the upgrade request, so the same cookie that authenticates
    HTTP routes also identifies the socket. The play surface needs a ready account, so a session
    that is unauthenticated, unnamed, or not-yet-approved yields None — the signal to close the
    handshake.
    """
    token = websocket.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user = await asyncio.to_thread(_resolve_user, token)
    if user is None or not user.get("display_name") or not user.get("is_approved"):
        return None
    return user


@router.get("/auth/login")
@limiter.limit("30/minute")
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

    result = await asyncio.to_thread(_complete_login, claims)
    if result is None:
        raise HTTPException(status_code=403, detail="This account is banned")
    token, user = result

    # A new or still-pending account lands on settings (the name picker / pending-approval notice);
    # a returning, approved account goes where it asked, or to the default landing. The admin is
    # notified once the new account picks a name (see update_me), not here — there is no name yet.
    landing = (
        "/settings"
        if user["created"] or user["display_name"] is None or not user["is_approved"]
        else _safe_next(login_state.get("redirect_to")) or DEFAULT_LANDING
    )
    response = RedirectResponse(landing, status_code=302)
    _set_session_cookie(response, request, token)
    return response


def _set_session_cookie(response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=_is_secure(request),
        samesite="lax",
        path="/",
    )


def _dev_login_enabled() -> bool:
    """Whether the dev sign-in shortcut is active: opt-in via env and never in production."""
    return bool(os.environ.get(DEV_LOGIN_ENV)) and os.environ.get("ENVIRONMENT") != "production"


def _dev_session(who: str | None) -> str:
    sub = f"dev-{who}" if who else "dev-local-user"
    name = who.title() if who else "Dev Player"
    with get_accounts_connection() as conn:
        user = users.upsert_user(conn, sub, f"{who or 'dev'}@localhost", True, name)
        users.set_approved(conn, user["id"], True)  # dev sessions skip the approval gate
        return sessions.create_session(conn, user["id"], SESSION_TTL)


@router.get("/auth/dev-login")
async def dev_login(request: Request):
    """Mint a session without Google, for local development.

    Refused with 404 (as if the route did not exist) unless ``YASUKI_DEV_LOGIN`` is set and the app
    is not in production, so it can never become a backdoor in a deployed environment. An optional
    ``?as=<name>`` query selects a distinct dev identity, so several can be signed in at once (two
    browsers for a local game); omitting it yields the default "Dev Player".
    """
    if not _dev_login_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    token = await asyncio.to_thread(_dev_session, request.query_params.get("as"))
    response = RedirectResponse(DEFAULT_LANDING, status_code=302)
    _set_session_cookie(response, request, token)
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


class DisplayNameUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)


class RoleUpdate(BaseModel):
    role: str = Field(min_length=1, max_length=64)


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=200)


class CropBox(BaseModel):
    left: float = Field(ge=0, le=1)
    top: float = Field(ge=0, le=1)
    right: float = Field(ge=0, le=1)
    bottom: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> "CropBox":
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("crop box must have left < right and top < bottom")
        return self


class AvatarRequest(BaseModel):
    card_id: str = Field(min_length=1, max_length=120)
    crop: CropBox


def _public_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "avatar": user.get("avatar"),
        "role": user.get("role", "user"),
        "is_approved": bool(user.get("is_approved")),
    }


@router.get("/api/me")
async def me(user: dict | None = Depends(current_user_optional)):
    return {"user": _public_user(user) if user else None}


@router.patch("/api/me")
async def update_me(request: Request, body: DisplayNameUpdate, user: dict = Depends(current_user)):
    """Change the signed-in user's display name.

    The first time a nameless new account sets a name it finishes onboarding, so the admin is
    notified that it is awaiting approval — with the name they chose. A later rename does not
    re-notify.
    """
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Display name cannot be blank")
    onboarding = user.get("display_name") is None
    updated = await asyncio.to_thread(_set_display_name, user["id"], name)
    if onboarding:
        # Fire-and-forget: a failed or unconfigured notification must never delay or break the save.
        approve_url = str(request.base_url).rstrip("/") + "/settings#admin"
        asyncio.create_task(
            asyncio.to_thread(notify_new_signup, updated["display_name"], approve_url)
        )
    return {"user": _public_user(updated)}


def _set_display_name(user_id: int, display_name: str) -> dict:
    with get_accounts_connection() as conn:
        return users.set_display_name(conn, user_id, display_name)


@router.post("/api/me/avatar")
async def set_my_avatar(request: Request, body: AvatarRequest, user: dict = Depends(current_user)):
    """Set the signed-in user's avatar to a crop of a chosen card.

    The card's image path is resolved server-side from ``card_id`` (rejecting an unknown card), so a
    client never supplies an arbitrary image path; the path is stored alongside the crop so rendering
    needs no further card-DB lookup.
    """
    image_path = await asyncio.to_thread(_card_image_path, body.card_id)
    if image_path is None:
        raise HTTPException(status_code=400, detail="Unknown card")
    spec = {"card_id": body.card_id, "image_path": image_path, "crop": body.crop.model_dump()}
    updated = await asyncio.to_thread(_save_avatar, user["id"], spec)
    return {"user": _public_user(updated)}


@router.delete("/api/me/avatar")
async def clear_my_avatar(request: Request, user: dict = Depends(current_user)):
    """Clear the avatar, falling the display back to the name's initials."""
    updated = await asyncio.to_thread(_save_avatar, user["id"], None)
    return {"user": _public_user(updated)}


def _card_image_path(card_id: str) -> str | None:
    card = get_card_by_id(card_id)
    return card["image_path"] if card else None


def _save_avatar(user_id: int, spec: dict | None) -> dict:
    with get_accounts_connection() as conn:
        return users.set_avatar(conn, user_id, spec)


@router.delete("/api/me")
async def delete_me(request: Request, user: dict = Depends(current_user)):
    """Erase the signed-in user's account (decks and sessions included) and clear the cookie."""
    await asyncio.to_thread(_delete_account, user["id"])
    response = JSONResponse({"deleted": True})
    response.delete_cookie(
        SESSION_COOKIE, path="/", httponly=True, secure=_is_secure(request), samesite="lax"
    )
    return response


@router.get("/api/admin/users")
async def admin_list_users(admin: dict = Depends(require_admin)):
    """Every account, for the admin dashboard. Admin-only; carries no email."""
    return {"users": await asyncio.to_thread(_list_users)}


@router.post("/api/admin/users/{user_id}/ban")
async def admin_ban_user(user_id: int, admin: dict = Depends(require_admin)):
    """Ban an account: revoke its sessions and tombstone the identity. Admin-only.

    Banning your own account is refused, since it would revoke the session you are acting through
    and lock you out.
    """
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot ban your own account")
    if not await asyncio.to_thread(_ban_user, user_id):
        raise HTTPException(status_code=404, detail="No such account")
    return {"banned": True}


@router.post("/api/admin/users/{user_id}/unban")
async def admin_unban_user(user_id: int, admin: dict = Depends(require_admin)):
    """Lift a ban so the identity may sign in again. Admin-only."""
    if not await asyncio.to_thread(_unban_user, user_id):
        raise HTTPException(status_code=404, detail="No such account")
    return {"unbanned": True}


@router.post("/api/admin/users/{user_id}/approve")
async def admin_approve_user(user_id: int, admin: dict = Depends(require_admin)):
    """Approve a pending account so it can use the product surfaces. Admin-only."""
    if not await asyncio.to_thread(_set_approved, user_id, True):
        raise HTTPException(status_code=404, detail="No such account")
    return {"approved": True}


@router.post("/api/admin/users/{user_id}/role")
async def admin_set_role(user_id: int, body: RoleUpdate, admin: dict = Depends(require_admin)):
    """Set an account's role to one of the defined roles (422 if it is not defined). Admin-only.

    Changing your own role is refused, so an admin cannot demote themselves out of the dashboard.
    """
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    role = body.role.strip().lower()
    if not await asyncio.to_thread(_role_exists, role):
        raise HTTPException(status_code=422, detail="Unknown role")
    if not await asyncio.to_thread(_set_role, user_id, role):
        raise HTTPException(status_code=404, detail="No such account")
    return {"role": role}


@router.get("/api/admin/roles")
async def admin_list_roles(admin: dict = Depends(require_admin)):
    """The defined roles, for the dashboard's role picker. Admin-only."""
    return {"roles": await asyncio.to_thread(_list_roles)}


@router.post("/api/admin/roles")
async def admin_create_role(body: RoleCreate, admin: dict = Depends(require_admin)):
    """Define a new role (a short lowercase slug) so it can be assigned. Admin-only.

    Returns the full role list so the caller can refresh its picker. Creating a role that already
    exists is a no-op, not an error.
    """
    name = body.name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name):
        raise HTTPException(status_code=422, detail="Role must be a short lowercase slug")
    await asyncio.to_thread(_create_role, name, body.description.strip())
    return {"roles": await asyncio.to_thread(_list_roles)}


def _list_users() -> list[dict]:
    with get_accounts_connection() as conn:
        return users.list_users(conn)


def _ban_user(user_id: int) -> bool:
    with get_accounts_connection() as conn:
        return users.ban_user(conn, user_id)


def _unban_user(user_id: int) -> bool:
    with get_accounts_connection() as conn:
        return users.unban_user(conn, user_id)


def _set_role(user_id: int, role: str) -> bool:
    with get_accounts_connection() as conn:
        return users.set_role(conn, user_id, role)


def _set_approved(user_id: int, approved: bool) -> bool:
    with get_accounts_connection() as conn:
        return users.set_approved(conn, user_id, approved)


def _role_exists(role: str) -> bool:
    with get_accounts_connection() as conn:
        return roles.role_exists(conn, role)


def _list_roles() -> list[dict]:
    with get_accounts_connection() as conn:
        return roles.list_roles(conn)


def _create_role(name: str, description: str) -> bool:
    with get_accounts_connection() as conn:
        return roles.create_role(conn, name, description)
