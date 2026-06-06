import pytest


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
