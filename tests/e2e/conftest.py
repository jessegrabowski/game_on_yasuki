import os
import socket
import subprocess
import sys
import time
import urllib.request

import psycopg
import pytest

from yasuki_core.accounts.db import accounts_connection_string

# Play is login-required, so the e2e signs each browser in through the dev-login bypass; that needs
# the accounts DB and a pepper, both supplied to the server below.
E2E_PEPPER = "e2e-test-pepper"

# Wrap the browser's WebSocket so a test can reach the room socket the page opens (window.__ws).
# Used only to seed a card with a SPAWN_CARD intent — there is no DB-free UI path to put a card on
# the table — so the drag interactions the test actually exercises run against the real client.
WS_CAPTURE_SCRIPT = """
const Native = window.WebSocket;
class Captured extends Native {
  constructor(...args) { super(...args); window.__ws = this; }
}
window.WebSocket = Captured;
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_health(base_url: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except OSError as err:
            last_error = err
            time.sleep(0.2)
    raise RuntimeError(f"server at {base_url} never became healthy: {last_error}")


def _accounts_db_available() -> bool:
    try:
        psycopg.connect(accounts_connection_string(), connect_timeout=5).close()
        return True
    except psycopg.OperationalError:
        return False


@pytest.fixture(scope="session")
def live_server() -> str:
    """A real uvicorn server on its own port with the dev-login bypass enabled.

    Play is login-required, so each browser signs in via /auth/dev-login, which needs the accounts
    DB; the suite skips when it is unreachable. The board state itself stays in-memory.
    """
    if not _accounts_db_available():
        pytest.skip("accounts database not reachable for e2e login")
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "YASUKI_DEV_LOGIN": "1", "YASUKI_EMAIL_HMAC_PEPPER": E2E_PEPPER}
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "yasuki_web.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
    )
    try:
        _wait_for_health(base_url)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
def new_player(browser, live_server):
    """Factory: open the signed-in play page for one player in its own browser context (own viewport
    and dev identity), with the room socket captured on window.__ws. Returns the Playwright page."""
    contexts = []

    def _open(viewport: dict):
        context = browser.new_context(base_url=live_server, viewport=viewport)
        contexts.append(context)
        page = context.new_page()
        page.add_init_script(WS_CAPTURE_SCRIPT)
        # Each player is a distinct dev identity so two browsers seat as P1 and P2, not one shared
        # account; dev-login redirects to /play-online.
        page.goto(f"/auth/dev-login?as=player{len(contexts)}")
        # The lobby gates create/join on the identity from /api/me; wait for it before acting.
        page.wait_for_function(
            "document.getElementById('playerIdentity')?.textContent.includes('Playing as')"
        )
        return page

    yield _open
    for context in contexts:
        context.close()
