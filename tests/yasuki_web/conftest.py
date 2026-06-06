import pytest


@pytest.fixture(autouse=True)
def _disable_http_rate_limit():
    """Disable the slowapi limiter for unit tests.

    The limiter keys on client IP with in-process state that persists across tests, so creating many
    rooms in one session would spuriously trip the 10/min create-room cap. None of these tests assert
    on HTTP rate limiting (the limit is verified separately); the WebSocket flood test uses its own
    token bucket and is unaffected.
    """
    from yasuki_web.rate_limit import limiter

    previously_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previously_enabled
