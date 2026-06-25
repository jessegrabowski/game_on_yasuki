from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from pydantic import ValidationError

from yasuki_web.config import allowed_origins
from yasuki_web.schemas import ClientMessage, ServerHello, ServerState, ServerError
from yasuki_web.rooms import rooms
from yasuki_web.wip_gate import websocket_access_ok

logger = logging.getLogger(__name__)
router = APIRouter()

connections: dict[str, set[WebSocket]] = {}
ip_connections: dict[str, int] = {}
MAX_CONNECTIONS_PER_IP = 5


class GameRoom:
    """
    Manages game state and player connections for a multiplayer room.

    This is where the actual game logic lives. Currently a simple state
    broadcaster, but you'll integrate your game engine here.
    """

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.players: dict[WebSocket, str] = {}
        self.game_state = {
            "turn": 0,
            "phase": "setup",
            "player_states": {},
        }
        self.seq = 0

    async def add_player(self, ws: WebSocket, player_name: str):
        """Add a player to the room and initialize their game state."""
        self.players[ws] = player_name
        self.game_state["player_states"][player_name] = {
            "hand": [],
            "battlefield": [],
            "provinces": [],
            "dynasty_deck_size": 40,
            "fate_deck_size": 40,
            "honor": 10,
            "ready": False,
        }

        rooms[self.room_id]["players"].append(player_name)

        hello = ServerHello(
            room=self.room_id,
            you=player_name,
            players=list(self.players.values()),
            seq=self.seq,
        )
        await ws.send_json(hello.model_dump())

        logger.info(f"Player {player_name} joined room {self.room_id}")

        await self.broadcast_state()

    async def remove_player(self, ws: WebSocket):
        """Remove a player from the room when they disconnect."""
        if ws in self.players:
            player_name = self.players.pop(ws)
            if player_name in self.game_state["player_states"]:
                del self.game_state["player_states"][player_name]

            if self.room_id in rooms:
                if player_name in rooms[self.room_id]["players"]:
                    rooms[self.room_id]["players"].remove(player_name)

            logger.info(f"Player {player_name} left room {self.room_id}")

            await self.broadcast_state()

    async def handle_action(self, ws: WebSocket, action: dict):
        """
        Process a game action from a player.

        TODO: Integrate with your actual game engine (app/engine/).
        For now, just updates state and broadcasts.
        """
        player_name = self.players.get(ws)
        if not player_name:
            return

        action_type = action.get("kind")

        if action_type == "PLAY_CARD":
            card_id = action.get("card")
            logger.info(f"{player_name} played card {card_id}")
            self.game_state["last_action"] = {
                "player": player_name,
                "action": action_type,
                "card": card_id,
            }

        elif action_type == "DRAW":
            logger.info(f"{player_name} drew a card")
            self.game_state["last_action"] = {
                "player": player_name,
                "action": action_type,
            }

        elif action_type == "PASS":
            logger.info(f"{player_name} passed")
            self.game_state["turn"] += 1
            self.game_state["last_action"] = {
                "player": player_name,
                "action": action_type,
            }

        elif action_type == "SHUFFLE":
            deck_type = action.get("deck_type", "dynasty")
            logger.info(f"{player_name} shuffled {deck_type} deck")
            self.game_state["last_action"] = {
                "player": player_name,
                "action": action_type,
                "deck_type": deck_type,
            }

        self.seq += 1
        await self.broadcast_state()

    async def broadcast_state(self):
        """Send current game state to all connected players."""
        state_msg = ServerState(
            room=self.room_id,
            seq=self.seq,
            state=self.game_state,
        )

        disconnected = []
        for ws in self.players.keys():
            try:
                await ws.send_json(state_msg.model_dump())
            except Exception as e:
                logger.error(f"Failed to send state to player: {e}")
                disconnected.append(ws)

        for ws in disconnected:
            await self.remove_player(ws)


active_game_rooms: dict[str, GameRoom] = {}

ROOM_TTL = timedelta(hours=2)
EVICTION_INTERVAL = 300


async def evict_stale_rooms():
    while True:
        await asyncio.sleep(EVICTION_INTERVAL)
        now = datetime.now(timezone.utc)
        stale = [
            rid
            for rid, r in rooms.items()
            if not r["players"] and (now - datetime.fromisoformat(r["created_at"])) > ROOM_TTL
        ]
        for rid in stale:
            del rooms[rid]
            active_game_rooms.pop(rid, None)
            logger.info(f"Evicted stale room {rid}")


MAX_WS_MESSAGE_SIZE = 4096

# Per-connection message throttle (token bucket): generous for turn-based play, but a flooding
# client drains it and gets closed.
WS_MSG_BURST = 20
WS_MSG_REFILL_PER_SEC = 2

ALLOWED_WS_ORIGINS = frozenset(allowed_origins())


def _origin_allowed(websocket: WebSocket) -> bool:
    """Reject cross-origin browser handshakes from sites not on the allowlist (CSWSH defense).

    A missing Origin header (native clients) and same-origin requests (the page that opened the
    socket is served by this app) are allowed; browsers always send Origin on cross-site connects.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    if origin in ALLOWED_WS_ORIGINS:
        return True
    host = websocket.headers.get("host")
    return bool(host) and urlparse(origin).netloc == host


def _refill(tokens: float, last: float) -> tuple[float, float]:
    now = time.monotonic()
    return min(WS_MSG_BURST, tokens + (now - last) * WS_MSG_REFILL_PER_SEC), now


@router.websocket("/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    if not _origin_allowed(websocket):
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    # WIP gate: the socket carries the page's cached Basic credentials. Closed unless they match (or
    # entirely when no password is configured). Dropped at the launch cutover.
    if not websocket_access_ok(websocket):
        await websocket.close(code=4401, reason="Unauthorized")
        return

    if room_id not in rooms:
        await websocket.close(code=4004, reason="Room not found")
        return

    room = rooms[room_id]
    if len(room["players"]) >= room["max_players"]:
        await websocket.close(code=4003, reason="Room full")
        return

    client_ip = websocket.client.host if websocket.client else "unknown"
    if ip_connections.get(client_ip, 0) >= MAX_CONNECTIONS_PER_IP:
        await websocket.close(code=4029, reason="Too many connections")
        return

    await websocket.accept()
    ip_connections[client_ip] = ip_connections.get(client_ip, 0) + 1

    if room_id not in active_game_rooms:
        active_game_rooms[room_id] = GameRoom(room_id)

    game_room = active_game_rooms[room_id]
    player_name = None

    tokens = float(WS_MSG_BURST)
    last_refill = time.monotonic()

    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > MAX_WS_MESSAGE_SIZE:
                await websocket.close(code=1009, reason="Message too large")
                return

            tokens, last_refill = _refill(tokens, last_refill)
            if tokens < 1:
                await websocket.close(code=1008, reason="Rate limit exceeded")
                return
            tokens -= 1

            try:
                message = ClientMessage.model_validate_json(data)
            except ValidationError:
                await websocket.close(code=1003, reason="Invalid message")
                return

            if message.type == "JOIN":
                if message.join is None:
                    await websocket.close(code=1003, reason="JOIN requires a name")
                    return
                player_name = message.join.name
                await game_room.add_player(websocket, player_name)

            elif message.type == "ACTION":
                if message.action is not None:
                    await game_room.handle_action(
                        websocket, message.action.model_dump(exclude_none=True)
                    )

            elif message.type == "PING":
                await websocket.send_json({"type": "PONG"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for player {player_name} in room {room_id}")
        if player_name:
            await game_room.remove_player(websocket)

    except Exception as e:
        logger.error(f"WebSocket error in room {room_id}: {e}", exc_info=True)
        error = ServerError(
            room=room_id,
            message="An internal error occurred",
        )
        try:
            await websocket.send_json(error.model_dump())
        except Exception:
            pass

    finally:
        ip_connections[client_ip] = max(0, ip_connections.get(client_ip, 1) - 1)
        if websocket in game_room.players:
            await game_room.remove_player(websocket)
