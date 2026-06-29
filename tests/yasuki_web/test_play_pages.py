from fastapi.testclient import TestClient

from yasuki_web.main import app

client = TestClient(app)


def test_play_online_serves_the_play_app():
    r = client.get("/play-online")
    assert r.status_code == 200
    assert "/site/play-online.js" in r.text


def test_the_retired_top_secret_route_is_gone():
    assert client.get("/top-secret.html").status_code == 404


def test_settings_page_served():
    r = client.get("/settings")
    assert r.status_code == 200
    assert "/site/settings.js" in r.text
