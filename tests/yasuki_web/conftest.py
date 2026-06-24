import base64

import pytest
from fastapi.testclient import TestClient

from yasuki_web.main import app
from yasuki_web.wip_gate import WIP_USERNAME

# A fixed password for the WIP gate so the rooms API and WS handshake are reachable in tests. The
# gate fails closed when unset, so without this every gated route would 404/close.
WIP_TEST_PASSWORD = "test-wip-password"
WIP_AUTH_HEADER = {
    "Authorization": "Basic "
    + base64.b64encode(f"{WIP_USERNAME}:{WIP_TEST_PASSWORD}".encode()).decode()
}


@pytest.fixture(autouse=True)
def _set_wip_password(monkeypatch):
    monkeypatch.setenv("WIP_PLAY_PASSWORD", WIP_TEST_PASSWORD)


@pytest.fixture
def wip_auth_header():
    return dict(WIP_AUTH_HEADER)


@pytest.fixture
def client(wip_auth_header):
    # Authenticated against the WIP gate by default. Tests of the gate itself override this with an
    # unauthenticated client.
    c = TestClient(app)
    c.headers.update(wip_auth_header)
    return c


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
