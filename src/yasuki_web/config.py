import os

_DEFAULT_ORIGINS = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]


def allowed_origins() -> list[str]:
    """The browser origins permitted to call the API and open WebSockets.

    Read from the comma-separated ``CORS_ORIGINS`` env var, falling back to the local dev front-end
    ports. Raise ValueError on a ``*`` entry: both the CORS layer and the WebSocket origin check
    rely on a concrete allowlist, so a wildcard is rejected outright.
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()] if raw else list(_DEFAULT_ORIGINS)
    if "*" in origins:
        raise ValueError("CORS_ORIGINS must not contain '*'. List explicit origins instead.")
    return origins
