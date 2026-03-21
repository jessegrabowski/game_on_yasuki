from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import secrets
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter()

rooms: dict[str, dict] = {}


def public_room(room: dict) -> dict:
    return {k: v for k, v in room.items() if k != "delete_token"}


class CreateRoomRequest(BaseModel):
    room_name: str | None = Field(None, description="Optional custom name for the room")
    max_players: int = Field(2, ge=2, le=4, description="Maximum number of players (2-4)")


class JoinRoomRequest(BaseModel):
    player_name: str = Field(..., min_length=1, max_length=50, description="Player display name")


@router.post("/rooms", status_code=201)
async def create_room(request: CreateRoomRequest):
    """
    Create a new game room.

    Returns a room_id that players use to join via WebSocket.
    Room remains active until all players disconnect or it's explicitly deleted.
    """
    room_id = secrets.token_urlsafe(8)
    delete_token = secrets.token_urlsafe(16)

    rooms[room_id] = {
        "id": room_id,
        "name": request.room_name or f"Room {room_id}",
        "max_players": request.max_players,
        "players": [],
        "state": "waiting",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "delete_token": delete_token,
    }

    logger.info(f"Created room {room_id}: {rooms[room_id]['name']}")

    return {
        "room_id": room_id,
        "room": public_room(rooms[room_id]),
        "delete_token": delete_token,
        "websocket_url": f"/ws/{room_id}",
    }


@router.get("/rooms")
async def list_rooms():
    """
    List all available game rooms.

    Only returns rooms in 'waiting' state that aren't full.
    Use this for matchmaking or lobby browsing.
    """
    available_rooms = [
        public_room(room)
        for room in rooms.values()
        if room["state"] == "waiting" and len(room["players"]) < room["max_players"]
    ]

    return {
        "rooms": available_rooms,
        "count": len(available_rooms),
        "total_rooms": len(rooms),
    }


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    """
    Get information about a specific room.

    Returns room metadata including current players and state.
    """
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")

    return {
        "room": public_room(rooms[room_id]),
        "websocket_url": f"/ws/{room_id}",
    }


@router.delete("/rooms/{room_id}")
async def delete_room(room_id: str, token: str = Query(...)):
    """
    Delete a room.

    Typically called when game ends or by admin for cleanup.
    All connected players will be disconnected.
    """
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    if rooms[room_id].get("delete_token") != token:
        raise HTTPException(status_code=403, detail="Forbidden")

    room_name = rooms[room_id]["name"]
    del rooms[room_id]

    logger.info(f"Deleted room {room_id}: {room_name}")

    return {
        "message": f"Room '{room_name}' deleted successfully",
        "room_id": room_id,
    }


@router.get("/rooms/{room_id}/players")
async def get_room_players(room_id: str):
    """
    Get list of players currently in a room.

    Useful for lobby UI to show who's in the room before joining.
    """
    if room_id not in rooms:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")

    room = rooms[room_id]

    return {
        "room_id": room_id,
        "players": room["players"],
        "player_count": len(room["players"]),
        "max_players": room["max_players"],
        "is_full": len(room["players"]) >= room["max_players"],
    }
