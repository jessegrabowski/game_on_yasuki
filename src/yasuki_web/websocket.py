from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from pydantic import ValidationError

from yasuki_web.config import allowed_origins
from yasuki_web.schemas import (
    ClientMessage,
    IntentEnvelope,
    SpawnRequest,
    intent_from_envelope,
    ServerHello,
    ServerSnapshot,
    ServerError,
    ServerChat,
    ServerLog,
)
from yasuki_web.snapshot import serialize_snapshot
from yasuki_web.rooms import rooms
from yasuki_web.wip_gate import websocket_access_ok

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import TableState, BoardPos, SpawnCard, RemoveCard
from yasuki_core.engine.action_log import ActionLog, InitialRecord, ChatEntry, apply_and_log
from yasuki_core.engine.redaction import redact
from yasuki_core.game_pieces.constants import Side

logger = logging.getLogger(__name__)
router = APIRouter()

connections: dict[str, set[WebSocket]] = {}
ip_connections: dict[str, int] = {}
MAX_CONNECTIONS_PER_IP = 5
HISTORY_LIMIT = 200


class GameRoom:
    """Authoritative game state and connections for one room.

    Owns a `TableState` (the truth) and an `ActionLog` (the durable tape of intents and chat). Each
    connection is bound to a seat (P1/P2); every accepted intent is applied through the core,
    recorded on the tape, and broadcast as a **per-viewer redacted** `SNAPSHOT` so a player never
    receives a card they are not entitled to see.
    """

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.players: dict[WebSocket, str] = {}
        self.seats: dict[WebSocket, PlayerId] = {}
        self.state = TableState.empty_two_seat()
        self.action_log = ActionLog(initial=InitialRecord.from_state(self.state))
        self._spawn_count = 0
        # Chat and log persist for the room's lifetime so a player who joins (or rejoins) sees what
        # came before. Capped to the most recent HISTORY_LIMIT of each.
        self.chat_history: list[dict] = []
        self.log_history: list[dict] = []

    def _free_seat(self) -> PlayerId | None:
        return next((s for s in PlayerId if s not in self.seats.values()), None)

    async def add_player(self, ws: WebSocket, player_name: str):
        """Seat a joining player (P1/P2), replay the room's chat and log history, and announce them.

        A connection with no free seat (a backstop behind the room's max-players cap) is told the
        table is full and left unseated.
        """
        seat = self._free_seat()
        if seat is None:
            await ws.send_json(ServerError(room=self.room_id, message="Table is full").model_dump())
            return

        self.seats[ws] = seat
        self.players[ws] = player_name
        self.state.seats[seat].name = player_name
        self.state.seats[seat].connected = True
        rooms[self.room_id]["players"].append(player_name)

        hello = ServerHello(
            room=self.room_id,
            you=player_name,
            your_seat=seat.name,
            players=list(self.players.values()),
            seq=self.state.seq,
        )
        await ws.send_json(hello.model_dump())

        for entry in self.log_history:
            await ws.send_json(entry)
        for entry in self.chat_history:
            await ws.send_json(entry)

        logger.info(f"Player {player_name} took seat {seat.name} in room {self.room_id}")

        await self.broadcast_snapshots()
        await self.log(f"{player_name} joined")

    async def remove_player(self, ws: WebSocket):
        """Free a player's seat on disconnect and announce the departure."""
        seat = self.seats.pop(ws, None)
        player_name = self.players.pop(ws, None)
        if seat is not None:
            self.state.seats[seat].connected = False

        if player_name:
            if self.room_id in rooms and player_name in rooms[self.room_id]["players"]:
                rooms[self.room_id]["players"].remove(player_name)
            logger.info(f"Player {player_name} left room {self.room_id}")
            await self.broadcast_snapshots()
            await self.log(f"{player_name} left")

    async def handle_intent(self, ws: WebSocket, envelope: IntentEnvelope):
        """Apply one intent for the acting seat through the authoritative core, record it, and
        broadcast. A malformed or unauthorized intent is rejected with `ERROR`, state unchanged."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        try:
            intent = intent_from_envelope(envelope)
        except (KeyError, ValueError, TypeError):
            await ws.send_json(
                ServerError(room=self.room_id, message="Invalid intent").model_dump()
            )
            return

        events = apply_and_log(self.state, self.action_log, seat, intent, ts=time.time())
        if not events:
            await ws.send_json(
                ServerError(room=self.room_id, message="Intent rejected").model_dump()
            )
            return
        await self.broadcast_snapshots()

    async def handle_spawn(self, ws: WebSocket, spawn: SpawnRequest):
        """Create a public, face-up card on the battlefield (tokens/copies/sandbox pieces) as a real
        logged `SpawnCard` intent. The server assigns the card id so a replay reproduces it."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        self._spawn_count += 1
        intent = SpawnCard(
            card_id=f"spawn-{self._spawn_count}",
            name=spawn.name,
            side=Side(spawn.side),
            image=spawn.img,
            position=BoardPos(float(spawn.x), float(spawn.y)),
        )
        if apply_and_log(self.state, self.action_log, seat, intent, ts=time.time()):
            await self.broadcast_snapshots()

    async def handle_remove(self, ws: WebSocket, card_id: str):
        """Remove a card from the table as a real logged `RemoveCard` intent."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        if apply_and_log(self.state, self.action_log, seat, RemoveCard(card_id), ts=time.time()):
            await self.broadcast_snapshots()

    async def broadcast_snapshots(self):
        """Send each seated player its own redacted `SNAPSHOT`. This is the per-viewer leak fix:
        the opponent's hand and face-down cards are stubs in the bytes that reach the wrong client."""
        disconnected = []
        for ws, seat in list(self.seats.items()):
            view = serialize_snapshot(redact(self.state, seat))
            try:
                await ws.send_json(ServerSnapshot(room=self.room_id, snapshot=view).model_dump())
            except Exception as e:
                logger.error(f"Failed to send snapshot: {e}")
                disconnected.append(ws)
        for ws in disconnected:
            await self.remove_player(ws)

    async def _broadcast(self, payload: dict):
        """Send one shared JSON payload (chat/log) to every connected player, evicting any that fail."""
        disconnected = []
        for ws in list(self.players):
            try:
                await ws.send_json(payload)
            except Exception as e:
                logger.error(f"Failed to send to player: {e}")
                disconnected.append(ws)
        for ws in disconnected:
            await self.remove_player(ws)

    @staticmethod
    def _append_capped(history: list[dict], entry: dict):
        history.append(entry)
        if len(history) > HISTORY_LIMIT:
            del history[:-HISTORY_LIMIT]

    async def handle_chat(self, ws: WebSocket, text: str):
        """Record a chat line on the durable tape and broadcast it to the whole room."""
        sender = self.players.get(ws)
        if not sender:
            return
        self.action_log.append(ChatEntry(ts=time.time(), sender=sender, text=text))
        payload = ServerChat(room=self.room_id, sender=sender, text=text).model_dump(by_alias=True)
        self._append_capped(self.chat_history, payload)
        await self._broadcast(payload)

    async def log(self, text: str):
        """Store and broadcast a game-log line to the whole room."""
        payload = ServerLog(room=self.room_id, text=text).model_dump()
        self._append_capped(self.log_history, payload)
        await self._broadcast(payload)


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

# Per-connection message throttle (token bucket). The refill must exceed the drag send rate
# (board.js DRAG_SEND_MS) or dragging a card drains the bucket and the server closes the socket; a
# genuine flood far above the refill still drains the burst and gets closed.
WS_MSG_BURST = 60
WS_MSG_REFILL_PER_SEC = 30

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

            elif message.type == "INTENT":
                if message.intent is not None:
                    await game_room.handle_intent(websocket, message.intent)

            elif message.type == "SPAWN":
                if message.spawn is not None:
                    await game_room.handle_spawn(websocket, message.spawn)

            elif message.type == "REMOVE":
                if message.remove is not None:
                    await game_room.handle_remove(websocket, message.remove.id)

            elif message.type == "CHAT":
                if message.chat is not None:
                    await game_room.handle_chat(websocket, message.chat.text)

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
