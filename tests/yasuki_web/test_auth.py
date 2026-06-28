import asyncio
import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from yasuki_core.accounts import users
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
    assert body["user"]["display_name"] == "Ada"
    assert "google_sub" not in body["user"]


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
