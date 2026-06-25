import pytest
from fastapi.testclient import TestClient

from yasuki_web.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_top_secret_page_served(client, wip_auth_header):
    r = client.get("/top-secret.html", headers=wip_auth_header)
    assert r.status_code == 200
    assert "/site/top-secret.js" in r.text


def test_play_online_still_placeholder(client):
    # The public route keeps the under-construction placeholder until the launch cutover.
    r = client.get("/play-online")
    assert r.status_code == 200
    assert "UNDER CONSTRUCTION" in r.text
