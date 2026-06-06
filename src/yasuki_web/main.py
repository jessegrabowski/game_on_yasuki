from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import asyncio
import logging
import os
from yasuki_web import cards, rooms, websocket
from yasuki_web.config import allowed_origins
from yasuki_web.rate_limit import limiter
from yasuki_web.websocket import evict_stale_rooms
from yasuki_core.database import close_pool
from yasuki_core.paths import BUNDLED_IMAGES_DIR, SETS_DIR


logger = logging.getLogger(__name__)

IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "/images")

_is_production = os.environ.get("ENVIRONMENT") == "production"

app = FastAPI(
    title="Game on, Yasuki! API",
    description="Online L5R card game server with WebSocket support for real-time multiplayer",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = allowed_origins()

# Reject oversized request bodies before they reach a route. Starlette buffers the whole body before
# Pydantic validates it, so without this a large POST is read into memory first. 64 KiB comfortably
# covers every JSON body the API accepts (the largest is a room-create payload).
MAX_REQUEST_BODY_BYTES = 64 * 1024


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                return Response("Invalid Content-Length", status_code=400)
            if declared > MAX_REQUEST_BODY_BYTES:
                return Response("Request body too large", status_code=413)
        return await call_next(request)


app.add_middleware(BodySizeLimitMiddleware)

# allow_credentials is False: the API uses no cookies/sessions, so browsers never need to send
# credentials cross-origin. Revisit if a cookie/token auth flow is added.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Delete-Token"],
)


# Card images come from the R2 CDN (https://*.r2.dev) or the local /images mount; fonts from Google.
# All page CSS and JS is served from same-origin static files, so styles and scripts stay 'self'.
_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "img-src 'self' https://*.r2.dev data:; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "script-src 'self' 'unsafe-inline'; "
    "connect-src 'self'"
)

# Public HTML pages and their static assets that the CSP applies to. The landing page lives at "/"
# (matched exactly), the rest by path prefix.
_CSP_PREFIXES = ("/deck-builder", "/site", "/card-search", "/play-online")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if forwarded_proto == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        path = request.url.path
        if path == "/" or path.startswith(_CSP_PREFIXES):
            response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
        return response


app.add_middleware(SecurityHeadersMiddleware)

DECK_BUILDER_DIR = Path(__file__).parent / "static" / "deck_builder"
SITE_DIR = Path(__file__).parent / "static" / "site"

if SITE_DIR.exists():
    app.mount("/site", StaticFiles(directory=SITE_DIR), name="site")

if SETS_DIR.exists():
    app.mount("/images/sets", StaticFiles(directory=SETS_DIR), name="sets")
    logger.info(f"Serving set images from {SETS_DIR}")
else:
    logger.warning(f"Sets directory not found at {SETS_DIR}")

if BUNDLED_IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=BUNDLED_IMAGES_DIR), name="images")
    logger.info(f"Serving bundled images from {BUNDLED_IMAGES_DIR}")
else:
    logger.warning(f"Bundled images directory not found at {BUNDLED_IMAGES_DIR}")

app.include_router(cards.router, prefix="/api", tags=["cards"])
app.include_router(rooms.router, prefix="/api", tags=["rooms"])
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])


def _site_page(filename: str) -> FileResponse:
    page = SITE_DIR / filename
    if not page.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(page)


@app.get("/")
async def root():
    index = SITE_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {
        "message": "Game on, Yasuki! API Server",
        "version": "1.0.0",
        "docs": "/docs",
        "deck_builder": "/deck-builder",
        "endpoints": {
            "cards": "/api/cards",
            "rooms": "/api/rooms",
            "websocket": "/ws/{room_id}",
        },
    }


@app.get("/card-search")
async def card_search():
    return _site_page("card-search.html")


@app.get("/play-online")
async def play_online():
    return _site_page("play-online.html")


@app.get("/api/config")
async def config():
    return {"image_base_url": IMAGE_BASE_URL}


if DECK_BUILDER_DIR.exists():
    app.mount(
        "/deck-builder", StaticFiles(directory=DECK_BUILDER_DIR, html=True), name="deck-builder"
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "game-on-yasuki"}


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(evict_stale_rooms())
    logger.info("Game on, Yasuki! API starting up...")
    logger.info("API Documentation available at: /docs")


@app.on_event("shutdown")
async def shutdown_event():
    close_pool()
    logger.info("Game on, Yasuki! API shutting down...")
