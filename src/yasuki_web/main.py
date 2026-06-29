from fastapi import Depends, FastAPI, HTTPException, Path as PathParam
from fastapi.responses import FileResponse, HTMLResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import asyncio
import logging
import os
import re
import psycopg
from yasuki_web import auth, cards, rooms, saved_decks, websocket
from yasuki_web.auth import require_approved
from yasuki_web.config import allowed_origins
from yasuki_web.rate_limit import limiter
from yasuki_web.websocket import evict_stale_rooms
from yasuki_core.accounts.db import close_accounts_pool
from yasuki_core.accounts.migrate import migrate as migrate_accounts_schema
from yasuki_core.database import close_pool, get_card_by_id, get_prints_by_card_id
from yasuki_core.paths import BUNDLED_IMAGES_DIR, SETS_DIR
from html import escape as html_escape
from typing import Annotated


logger = logging.getLogger(__name__)

IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "/images")

_is_production = os.environ.get("ENVIRONMENT") == "production"

# Truthy DEBUG (uvicorn launches via the pixi `api` task, so there is no custom CLI flag) tells the
# client to surface debug-level server errors such as rejected intents in the game log.
_debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(app: FastAPI):
    eviction = asyncio.create_task(evict_stale_rooms())
    logger.info("Game on, Yasuki! API starting up...")
    logger.info("API Documentation available at: /docs")
    # Ensure the accounts schema exists (idempotent; never drops). Best-effort: an unreachable
    # accounts DB must not take down the fully public card-search / deck-builder surface, so log and
    # continue — account features degrade until it recovers, and the migration re-runs next boot. A
    # non-connection failure (e.g. a real DDL bug) still propagates and fails the deploy loudly.
    try:
        await asyncio.to_thread(migrate_accounts_schema)
    except psycopg.OperationalError:
        logger.exception("Accounts DB unreachable at startup; account features degraded")
    try:
        yield
    finally:
        eviction.cancel()
        close_pool()
        close_accounts_pool()
        logger.info("Game on, Yasuki! API shutting down...")


app = FastAPI(
    title="Game on, Yasuki! API",
    description="Online L5R card game server with WebSocket support for real-time multiplayer",
    version="1.0.0",
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    lifespan=lifespan,
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

# allow_credentials is True so the browser sends the session cookie on same-origin and allowed
# cross-origin requests. This is safe only against a concrete origin allowlist — never "*" — which
# allowed_origins() enforces by rejecting a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
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
_CSP_PREFIXES = (
    "/deck_builder",
    "/site",
    "/card-search",
    "/card/",
    "/play",
    "/syntax",
    "/privacy",
    "/settings",
)


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
# Saved decks are part of the public deck-builder surface, not the WIP play backend, so they carry no
# WIP gate; owner routes (/api/me/decks) require a session, public reads (/api/decks/{slug}) are
# visibility-checked.
app.include_router(saved_decks.router, prefix="/api", tags=["decks"])
# Play is login-required: the whole rooms API needs a session, matching the WS handshake's own
# login gate (websocket.py). Anonymous visitors can browse cards and build decks, not create or
# join games.
app.include_router(
    rooms.router, prefix="/api", tags=["rooms"], dependencies=[Depends(require_approved)]
)
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])
# Auth routes carry their own full paths (/auth/*, /api/me) and gate nothing themselves — the
# session cookie is additive, ignored on public routes and required only where a route depends on
# current_user.
app.include_router(auth.router, tags=["auth"])


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
        "deck_builder": "/deck_builder",
        "endpoints": {
            "cards": "/api/cards",
            "rooms": "/api/rooms",
            "websocket": "/ws/{room_id}",
        },
    }


@app.get("/card-search")
async def card_search():
    return _site_page("card-search.html")


@app.get("/play")
async def play():
    return _site_page("play-online.html")


@app.get("/syntax")
async def syntax():
    return _site_page("syntax.html")


@app.get("/privacy")
async def privacy():
    return _site_page("privacy.html")


@app.get("/settings")
async def settings():
    return _site_page("settings.html")


_SLUG = r"^[a-z0-9_-]+$"
_CardId = Annotated[str, PathParam(max_length=120, pattern=_SLUG)]
_SetSlug = Annotated[str, PathParam(max_length=120, pattern=_SLUG)]


def _absolute_image_url(image_path: str, request: Request) -> str:
    """Build an absolute URL for a card image, for crawler-readable og:image tags.

    ``IMAGE_BASE_URL`` is already absolute in production (the R2 CDN); locally it is the relative
    ``/images`` mount, so join it onto the request's own origin.
    """
    if IMAGE_BASE_URL.startswith("http"):
        return f"{IMAGE_BASE_URL}/{image_path}"
    return f"{str(request.base_url).rstrip('/')}{IMAGE_BASE_URL}/{image_path}"


def _card_meta_tags(card: dict, print_: dict | None, canonical: str, request: Request) -> str:
    name = card["name"]
    descriptor = " · ".join(
        b for b in (" · ".join(card.get("types") or []), " · ".join(card.get("clans") or [])) if b
    )
    # Rules text carries simple inline markup (<b>, <br>); strip it for a clean unfurl snippet.
    rules = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", card.get("text") or "")).strip()
    description = (f"{descriptor}. {rules}" if descriptor and rules else descriptor or rules)[:200]
    e = html_escape
    tags = [
        f"<title>{e(name)} &mdash; Game on, Yasuki!</title>",
        f'<link rel="canonical" href="{e(canonical)}">',
        '<meta property="og:type" content="website">',
        f'<meta property="og:url" content="{e(canonical)}">',
        f'<meta property="og:title" content="{e(name)}">',
        f'<meta name="description" content="{e(description)}">',
        f'<meta property="og:description" content="{e(description)}">',
        '<meta name="twitter:card" content="summary_large_image">',
    ]
    if print_ and print_.get("image_path"):
        image = _absolute_image_url(print_["image_path"], request)
        tags.append(f'<meta property="og:image" content="{e(image)}">')
        tags.append(f'<meta name="twitter:image" content="{e(image)}">')
    return "\n".join(tags)


async def _render_card_page(card_id: str, set_slug: str | None, request: Request) -> HTMLResponse:
    card = await asyncio.to_thread(get_card_by_id, card_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"Card '{card_id}' not found")
    prints = await asyncio.to_thread(get_prints_by_card_id, card_id)

    selected = next((p for p in prints if p["set_slug"] == set_slug), None) if set_slug else None
    if selected is None:
        selected = prints[0] if prints else None

    canonical_path = f"/card/{card_id}/{selected['set_slug']}" if selected else f"/card/{card_id}"
    canonical = f"{str(request.base_url).rstrip('/')}{canonical_path}"

    shell = (SITE_DIR / "card.html").read_text(encoding="utf-8")
    html = shell.replace("<!--META-->", _card_meta_tags(card, selected, canonical, request))
    return HTMLResponse(html)


@app.get("/card/{card_id}")
async def card_page(request: Request, card_id: _CardId):
    return await _render_card_page(card_id, None, request)


@app.get("/card/{card_id}/{set_slug}")
async def card_page_print(request: Request, card_id: _CardId, set_slug: _SetSlug):
    return await _render_card_page(card_id, set_slug, request)


@app.get("/api/config")
async def config():
    return {"image_base_url": IMAGE_BASE_URL, "debug": _debug}


if DECK_BUILDER_DIR.exists():
    app.mount(
        "/deck_builder", StaticFiles(directory=DECK_BUILDER_DIR, html=True), name="deck_builder"
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "game-on-yasuki"}
