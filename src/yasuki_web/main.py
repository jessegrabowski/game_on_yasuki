from fastapi import FastAPI
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

_default_origins = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
_cors_origins = (
    [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
    if os.environ.get("CORS_ORIGINS")
    else _default_origins
)
if "*" in _cors_origins:
    raise ValueError(
        "CORS_ORIGINS must not contain '*' when allow_credentials=True. "
        "List explicit origins instead."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
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
        if request.url.path.startswith("/deck-builder"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' https://*.r2.dev data:; "
                "style-src 'self' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; "
                "script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)

DECK_BUILDER_DIR = Path(__file__).parent / "static" / "deck_builder"

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


@app.get("/")
async def root():
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
