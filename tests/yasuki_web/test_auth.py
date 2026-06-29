import asyncio
import base64
import hashlib
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from yasuki_core.accounts import banlist, users
from yasuki_web import auth
from yasuki_web.main import app

CLIENT_ID = "client-123"


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _mint(
    private_key,
    *,
    nonce,
    sub="google-sub-1",
    email="ada@example.com",
    email_verified=True,
    name="Ada",
    iss="https://accounts.google.com",
    aud=CLIENT_ID,
    expires_in=timedelta(hours=1),
):
    now = datetime.now(timezone.utc)
    payload = {
        "iss": iss,
        "aud": aud,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": name,
        "picture": "http://pic",
        "nonce": nonce,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def client(monkeypatch, accounts_conn, rsa_key):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://testserver/auth/callback")
    monkeypatch.setenv("YASUKI_EMAIL_HMAC_PEPPER", "test-pepper")
    monkeypatch.setattr(auth, "_signing_key", lambda token: rsa_key.public_key())

    @contextmanager
    def fake_conn():
        yield accounts_conn

    monkeypatch.setattr(auth, "get_accounts_connection", fake_conn)
    with TestClient(app) as test_client:
        yield test_client


def _login_and_callback(
    client, monkeypatch, signer, *, override_nonce=None, callback_headers=None, **claim_overrides
):
    """Drive /auth/login, mint an id_token bound to that login's nonce, then hit /auth/callback.

    ``override_nonce`` mints a token whose nonce does not match the one bound at login, to exercise
    the binding check; ``callback_headers`` lets a test present a header such as a forwarded proto.
    """
    login_resp = client.get("/auth/login", follow_redirects=False)
    query = parse_qs(urlparse(login_resp.headers["location"]).query)
    nonce = override_nonce if override_nonce is not None else query["nonce"][0]
    token = _mint(signer, nonce=nonce, **claim_overrides)
    monkeypatch.setattr(auth, "_exchange_code", lambda code, verifier, config: token)
    return client.get(
        f"/auth/callback?code=x&state={query['state'][0]}",
        follow_redirects=False,
        headers=callback_headers,
    )


def test_me_is_anonymous_without_a_session(client):
    assert client.get("/api/me").json() == {"user": None}


def test_login_redirects_to_google_with_pkce_and_state(client):
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert query["client_id"] == [CLIENT_ID]
    assert query["state"] and query["nonce"]


def test_full_login_flow_sets_session_and_me_returns_user(client, monkeypatch, rsa_key):
    callback = _login_and_callback(client, monkeypatch, rsa_key)
    assert callback.status_code == 302
    assert "yasuki_session" in callback.cookies
    set_cookie = callback.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    body = client.get("/api/me").json()
    # The display name is a generated handle, never the Google profile name "Ada" — no real-name
    # leak — and the opaque google_sub is never exposed.
    assert body["user"]["display_name"] != "Ada"
    assert re.fullmatch(r"[A-Z][a-zA-Z]+\d{3}", body["user"]["display_name"])
    assert "google_sub" not in body["user"]


def test_first_login_redirects_to_settings_then_returning_logins_do_not(
    client, monkeypatch, rsa_key
):
    first = _login_and_callback(client, monkeypatch, rsa_key)
    assert first.headers["location"] == "/settings"
    client.post("/auth/logout")
    again = _login_and_callback(client, monkeypatch, rsa_key)
    assert again.headers["location"] != "/settings"


def test_update_me_changes_the_display_name(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    resp = client.patch("/api/me", json={"display_name": "Hida Kisada"})
    assert resp.status_code == 200
    assert resp.json()["user"]["display_name"] == "Hida Kisada"
    assert client.get("/api/me").json()["user"]["display_name"] == "Hida Kisada"


def test_update_me_requires_a_session(client):
    assert client.patch("/api/me", json={"display_name": "Anon"}).status_code == 401


def test_update_me_rejects_a_blank_or_overlong_name(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.patch("/api/me", json={"display_name": "   "}).status_code == 422
    assert client.patch("/api/me", json={"display_name": "N" * 41}).status_code == 422


def test_set_avatar_crops_a_card_resolving_its_image_server_side(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    monkeypatch.setattr(auth, "get_card_by_id", lambda cid: {"image_path": f"sets/x/{cid}.jpg"})
    crop = {"left": 0.1, "top": 0.15, "right": 0.4, "bottom": 0.45}
    # A client tries to smuggle its own image_path; the server must ignore it and use the card's.
    resp = client.post(
        "/api/me/avatar",
        json={"card_id": "doji-challenger", "image_path": "evil/path.jpg", "crop": crop},
    )
    assert resp.status_code == 200

    avatar = client.get("/api/me").json()["user"]["avatar"]
    assert avatar == {
        "card_id": "doji-challenger",
        "image_path": "sets/x/doji-challenger.jpg",  # derived from card_id, not the smuggled path
        "crop": crop,
    }


def test_set_avatar_rejects_an_unknown_card(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    monkeypatch.setattr(auth, "get_card_by_id", lambda cid: None)
    box = {"left": 0, "top": 0, "right": 1, "bottom": 1}
    assert client.post("/api/me/avatar", json={"card_id": "ghost", "crop": box}).status_code == 400


def test_set_avatar_rejects_a_degenerate_crop(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    monkeypatch.setattr(auth, "get_card_by_id", lambda cid: {"image_path": "x.jpg"})
    flat_x = {"left": 0.5, "top": 0, "right": 0.5, "bottom": 1}  # left == right
    flat_y = {"left": 0, "top": 0.5, "right": 1, "bottom": 0.5}  # top == bottom
    for box in (flat_x, flat_y):
        assert client.post("/api/me/avatar", json={"card_id": "d", "crop": box}).status_code == 422


def test_set_avatar_requires_a_session(client):
    box = {"left": 0, "top": 0, "right": 1, "bottom": 1}
    assert client.post("/api/me/avatar", json={"card_id": "x", "crop": box}).status_code == 401


def test_clear_avatar_falls_back_to_initials(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    monkeypatch.setattr(auth, "get_card_by_id", lambda cid: {"image_path": "x.jpg"})
    box = {"left": 0, "top": 0, "right": 1, "bottom": 1}
    client.post("/api/me/avatar", json={"card_id": "doji", "crop": box})
    assert client.delete("/api/me/avatar").status_code == 200
    assert client.get("/api/me").json()["user"]["avatar"] is None


def test_callback_rejects_unknown_state(client):
    resp = client.get("/auth/callback?code=x&state=never-issued", follow_redirects=False)
    assert resp.status_code == 400


def test_callback_rejects_unverified_email(client, monkeypatch, rsa_key):
    resp = _login_and_callback(client, monkeypatch, rsa_key, email_verified=False)
    assert resp.status_code == 403


def test_callback_rejects_a_banned_account(client, monkeypatch, accounts_conn, rsa_key):
    user = users.upsert_user(accounts_conn, "banned-sub", "ban@example.com", True, "Banned")
    with accounts_conn.cursor() as cur:
        cur.execute("UPDATE users SET is_banned = true WHERE id = %s", (user["id"],))
    resp = _login_and_callback(
        client, monkeypatch, rsa_key, sub="banned-sub", email="ban@example.com"
    )
    assert resp.status_code == 403


def test_callback_rejects_a_banlisted_identity_after_account_deletion(
    client, monkeypatch, accounts_conn, rsa_key
):
    # Ban then delete the account so only the banlist tombstone remains; the returning identity
    # (default sub/email minted by _login_and_callback) must still be refused.
    user = users.upsert_user(accounts_conn, "google-sub-1", "ada@example.com", True, "Ada")
    users.ban_user(accounts_conn, user["id"], "spam")
    users.delete_account(accounts_conn, user["id"])
    resp = _login_and_callback(client, monkeypatch, rsa_key)
    assert resp.status_code == 403


def test_delete_me_erases_the_account_and_clears_the_session(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.get("/api/me").json()["user"] is not None
    assert client.delete("/api/me").status_code == 200
    assert client.get("/api/me").json() == {"user": None}


def test_delete_me_requires_a_session(client):
    assert client.delete("/api/me").status_code == 401


def test_dev_login_is_absent_by_default(client):
    assert client.get("/auth/dev-login", follow_redirects=False).status_code == 404


def test_dev_login_mints_a_session_when_enabled(client, monkeypatch):
    monkeypatch.setenv("YASUKI_DEV_LOGIN", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    resp = client.get("/auth/dev-login", follow_redirects=False)
    assert resp.status_code == 302
    assert "yasuki_session" in resp.cookies
    assert client.get("/api/me").json()["user"]["display_name"] == "Dev Player"


def test_dev_login_is_refused_in_production_even_when_enabled(client, monkeypatch):
    monkeypatch.setenv("YASUKI_DEV_LOGIN", "1")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get("/auth/dev-login", follow_redirects=False).status_code == 404


def test_dev_login_as_param_selects_a_distinct_identity(client, monkeypatch):
    monkeypatch.setenv("YASUKI_DEV_LOGIN", "1")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    client.get("/auth/dev-login?as=kenji", follow_redirects=False)
    assert client.get("/api/me").json()["user"]["display_name"] == "Kenji"


def test_callback_rejects_a_token_signed_by_the_wrong_key(client, monkeypatch, other_rsa_key):
    resp = _login_and_callback(client, monkeypatch, other_rsa_key)
    assert resp.status_code == 400


def test_callback_rejects_wrong_audience(client, monkeypatch, rsa_key):
    resp = _login_and_callback(client, monkeypatch, rsa_key, aud="some-other-client")
    assert resp.status_code == 400


def test_callback_rejects_wrong_issuer(client, monkeypatch, rsa_key):
    resp = _login_and_callback(client, monkeypatch, rsa_key, iss="https://evil.example.com")
    assert resp.status_code == 400


def test_callback_rejects_expired_token(client, monkeypatch, rsa_key):
    resp = _login_and_callback(client, monkeypatch, rsa_key, expires_in=timedelta(minutes=-5))
    assert resp.status_code == 400


def test_callback_rejects_mismatched_nonce(client, monkeypatch, rsa_key):
    resp = _login_and_callback(client, monkeypatch, rsa_key, override_nonce="not-the-login-nonce")
    assert resp.status_code == 400


def test_callback_sets_a_secure_cookie_behind_https(client, monkeypatch, rsa_key):
    resp = _login_and_callback(
        client, monkeypatch, rsa_key, callback_headers={"x-forwarded-proto": "https"}
    )
    assert "secure" in resp.headers["set-cookie"].lower()


def test_logout_clears_the_session(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.get("/api/me").json()["user"] is not None
    client.post("/auth/logout", follow_redirects=False)
    assert client.get("/api/me").json() == {"user": None}


def test_current_user_rejects_an_anonymous_request():
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
    with pytest.raises(HTTPException) as raised:
        asyncio.run(auth.current_user(request))
    assert raised.value.status_code == 401


def test_pkce_pair_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = auth._pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode()
    assert challenge == expected.rstrip("=")


def _promote_to_admin(accounts_conn, user_id):
    with accounts_conn.cursor() as cur:
        cur.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user_id,))


def test_me_exposes_the_role(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.get("/api/me").json()["user"]["role"] == "user"


def test_admin_endpoints_require_a_session(client):
    assert client.get("/api/admin/users").status_code == 401


def test_admin_endpoints_are_forbidden_to_non_admins(client, monkeypatch, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.get("/api/admin/users").status_code == 403


def test_mutating_admin_endpoints_are_forbidden_to_non_admins(client, monkeypatch, rsa_key):
    # The read is gated above; pin that the mutations (far higher stakes) are gated too.
    _login_and_callback(client, monkeypatch, rsa_key)
    assert client.post("/api/admin/users/1/ban").status_code == 403
    assert client.post("/api/admin/users/1/role", json={"role": "admin"}).status_code == 403


def test_admin_lists_accounts_without_any_email(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])

    listed = client.get("/api/admin/users").json()["users"]
    assert any(u["display_name"] == me["display_name"] for u in listed)
    assert all("email" not in u and "email_hmac" not in u for u in listed)
    assert all("last_seen" in u for u in listed)


def test_admin_bans_then_unbans_another_account(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])
    target = users.upsert_user(accounts_conn, "google-target", "t@example.com", True, "Target")

    assert client.post(f"/api/admin/users/{target['id']}/ban").status_code == 200
    assert users.get_user(accounts_conn, target["id"])["is_banned"] is True
    assert banlist.is_banned(accounts_conn, "google-target", "t@example.com") is True

    assert client.post(f"/api/admin/users/{target['id']}/unban").status_code == 200
    assert users.get_user(accounts_conn, target["id"])["is_banned"] is False
    assert banlist.is_banned(accounts_conn, "google-target", "t@example.com") is False


def test_admin_cannot_ban_its_own_account(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])

    assert client.post(f"/api/admin/users/{me['id']}/ban").status_code == 400
    assert users.get_user(accounts_conn, me["id"])["is_banned"] is False


def test_admin_seeds_user_and_admin_roles(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    _promote_to_admin(accounts_conn, client.get("/api/me").json()["user"]["id"])

    names = {r["name"] for r in client.get("/api/admin/roles").json()["roles"]}
    assert {"user", "admin"} <= names


def test_admin_creates_a_role_then_assigns_it_normalizing_input(
    client, monkeypatch, accounts_conn, rsa_key
):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])
    target = users.upsert_user(accounts_conn, "google-mod", "m@example.com", True, "Minion")

    created = client.post("/api/admin/roles", json={"name": "Moderator"})
    assert created.status_code == 200
    assert "moderator" in {r["name"] for r in created.json()["roles"]}  # normalized to a slug

    resp = client.post(f"/api/admin/users/{target['id']}/role", json={"role": "Moderator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "moderator"
    assert users.get_user(accounts_conn, target["id"])["role"] == "moderator"


def test_set_role_rejects_an_undefined_role(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])
    target = users.upsert_user(accounts_conn, "google-x", "x@example.com", True, "X")

    resp = client.post(f"/api/admin/users/{target['id']}/role", json={"role": "ghost"})
    assert resp.status_code == 422
    assert users.get_user(accounts_conn, target["id"])["role"] == "user"


def test_create_role_rejects_a_non_slug_name(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    _promote_to_admin(accounts_conn, client.get("/api/me").json()["user"]["id"])
    assert client.post("/api/admin/roles", json={"name": "Bad Role!"}).status_code == 422


def test_admin_cannot_change_its_own_role(client, monkeypatch, accounts_conn, rsa_key):
    _login_and_callback(client, monkeypatch, rsa_key)
    me = client.get("/api/me").json()["user"]
    _promote_to_admin(accounts_conn, me["id"])

    assert (
        client.post(f"/api/admin/users/{me['id']}/role", json={"role": "user"}).status_code == 400
    )
    assert users.get_user(accounts_conn, me["id"])["role"] == "admin"
