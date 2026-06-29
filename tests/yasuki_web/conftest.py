import pytest
from fastapi.testclient import TestClient

from yasuki_web import auth
from yasuki_web.main import app


@pytest.fixture
def client():
    # The rooms API is login-required, so default to a signed-in session by overriding current_user.
    # Tests of the anonymous path clear the override or assert against the WS gate directly.
    app.dependency_overrides[auth.current_user] = lambda: {
        "id": 1,
        "display_name": "Ada",
        "avatar_url": None,
        "is_banned": False,
    }
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(auth.current_user, None)


@pytest.fixture(autouse=True)
def _fake_ws_auth(monkeypatch):
    """Authenticate WS handshakes from a per-connection header instead of the accounts database.

    Production resolves the session cookie against the accounts pool; here a connection names its
    player via the ``x-test-user`` header and gets a stable account for it, so seating logic is
    exercised without provisioning Postgres. Two connections naming the same player share an id —
    the second-tab case — while distinct names are distinct players. A connection with no header
    defaults to ``Ada``, the lone player the single-seat tests expect.
    """
    from yasuki_web import websocket as ws_module

    from tests.yasuki_web._support import WS_USER_HEADER, account

    async def fake_auth(websocket):
        return account(websocket.headers.get(WS_USER_HEADER, "Ada"))

    monkeypatch.setattr(ws_module, "_authenticate", fake_auth)


@pytest.fixture(autouse=True)
def _disable_http_rate_limit():
    """Disable the slowapi limiter for unit tests.

    Its per-IP counters persist in-process across tests, so creating many rooms in one session
    would spuriously trip the 10/min create-room cap. No test here asserts on HTTP rate limiting.
    """
    from yasuki_web.rate_limit import limiter

    previously_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previously_enabled
