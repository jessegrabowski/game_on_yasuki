from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging
import os
from app.api import cards, rooms, websocket

logger = logging.getLogger(__name__)

IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "/images")

app = FastAPI(
    title="Game on, Yasuki! API",
    description="Online L5R card game server with WebSocket support for real-time multiplayer",
    version="1.0.0",
)

_default_origins = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]
_cors_origins = (
    os.environ.get("CORS_ORIGINS", "").split(",")
    if os.environ.get("CORS_ORIGINS")
    else _default_origins
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
IMAGES_DIR = ASSETS_DIR / "images"
DECK_BUILDER_DIR = ASSETS_DIR / "deck_builder"

if IMAGES_DIR.exists():
    app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")
    logger.info(f"Serving card images from {IMAGES_DIR}")
else:
    logger.warning(f"Images directory not found at {IMAGES_DIR}")

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
    logger.info("Game on, Yasuki! API starting up...")
    logger.info("API Documentation available at: /docs")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Game on, Yasuki! API shutting down...")
