import os
import socket
import subprocess
import sys
import time
import urllib.request

import psycopg
import pytest

from yasuki_core.accounts.db import accounts_connection_string
from yasuki_core.database import get_connection_string

# Play is login-required, so the e2e signs each browser in through the dev-login bypass; that needs
# the accounts DB and a pepper, both supplied to the server below.
E2E_PEPPER = "e2e-test-pepper"

# Wrap the browser's WebSocket so a test can reach the room socket the page opens (window.__ws).
# Tests drive deck-load/ready and card intents straight onto this socket — there is no UI path for
# them — so the drag and flag interactions they actually exercise run against the real client.
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
    DB; the suite skips when it is unreachable. Board state stays in-memory, but the tests deal a
    real deck, so the server also reaches the cards database to resolve decks and creatable tokens.
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
        # account; dev-login redirects to /play.
        page.goto(f"/auth/dev-login?as=player{len(contexts)}")
        # The lobby gates create/join on the identity from /api/me; the nav pill renders
        # .account-name once that resolves, so wait for it before acting.
        page.wait_for_function("document.querySelector('.account-name')?.textContent")
        return page

    yield _open
    for context in contexts:
        context.close()


# Weapon Artist is a Holding that creates exactly one token; loading a deck of it populates the
# table's `creatable_tokens` so a SPAWN_CARD {token_id} resolves. Both e2e files lean on this.
CREATOR_CARD_ID = "weapon_artist"
TOKEN_CARD_ID = "weapon_item_sword_plus2f_plus1c"

# A minimal loadable deck: a stronghold to open provinces and a dynasty stack of nothing but Weapon
# Artist. parse_deck_yaml resolves card names against the database, so these must match real cards.
DECK_YAML = """\
name: Token Probe
Pre-Game:
  - Kyuden Hida
Dynasty:
  - 8x Weapon Artist
"""


def _token_db_ready() -> bool:
    """True when the cards database is reachable and carries the Weapon Artist creates edge."""
    try:
        with psycopg.connect(get_connection_string()) as conn:
            row = conn.execute(
                "SELECT 1 FROM card_creates WHERE creator_card_id = %s AND created_card_id = %s",
                (CREATOR_CARD_ID, TOKEN_CARD_ID),
            ).fetchone()
            return row is not None
    except Exception:
        return False


def create_room(page):
    """Create a room through the lobby UI and return its id; the room socket the page opens is
    captured on window.__ws by `new_player`."""
    page.click("#createForm button[type=submit]")
    page.wait_for_selector("#roomView:not([hidden])")
    room_id = page.inner_text("#roomIdLabel").strip()
    assert room_id, "room id label populated after creating a room"
    return room_id


def join_room(page, room_id):
    page.fill("#joinRoomId", room_id)
    page.click("#joinForm button[type=submit]")
    page.wait_for_selector("#roomView:not([hidden])")


def send(page, message):
    page.evaluate("(msg) => window.__ws.send(JSON.stringify(msg))", message)


def send_intent(page, room_id, intent):
    send(page, {"type": "INTENT", "room": room_id, "intent": intent})
