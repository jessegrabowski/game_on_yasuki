import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from yasuki_web.wip_gate import WIP_USERNAME

WIP_PASSWORD = "test-wip-password"

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


@pytest.fixture(scope="session")
def live_server() -> str:
    """A real uvicorn server with the WIP gate open, on its own port. No database is touched: the
    e2e flow never deals a deck, so the rooms/websocket layer runs standalone."""
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "WIP_PLAY_PASSWORD": WIP_PASSWORD}
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
    """Factory: open a board page for one player in its own browser context (own viewport and WIP
    credentials), with the room socket captured on window.__ws. Returns the Playwright page."""
    contexts = []

    def _open(viewport: dict):
        # Suppress the FLIP move animation so position assertions read the settled rect, not a card
        # mid-glide.
        context = browser.new_context(
            base_url=live_server,
            viewport=viewport,
            http_credentials={"username": WIP_USERNAME, "password": WIP_PASSWORD},
            reduced_motion="reduce",
        )
        contexts.append(context)
        page = context.new_page()
        page.add_init_script(WS_CAPTURE_SCRIPT)
        page.goto("/top-secret.html")
        return page

    yield _open
    for context in contexts:
        context.close()
