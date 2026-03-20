from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import logging

from app.schemas import ServerHello, ServerState, ServerError
from app.api.rooms import rooms

logger = logging.getLogger(__name__)
router = APIRouter()

connections: dict[str, set[WebSocket]] = {}


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


@router.websocket("/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    """
    WebSocket endpoint for real-time game communication.

    Protocol:
    1. Client connects to /ws/{room_id}
    2. Client sends JOIN message with player name
    3. Server sends HELLO with room info
    4. Clients exchange ACTION messages
    5. Server broadcasts STATE updates to all players

    See app/schemas.py for message formats.
    """
    await websocket.accept()

    if room_id not in active_game_rooms:
        active_game_rooms[room_id] = GameRoom(room_id)

    game_room = active_game_rooms[room_id]
    player_name = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            msg_type = message.get("type")

            if msg_type == "JOIN":
                join_data = message.get("join", {})
                player_name = join_data.get("name", "Anonymous")
                await game_room.add_player(websocket, player_name)

            elif msg_type == "ACTION":
                action = message.get("action", {})
                await game_room.handle_action(websocket, action)

            elif msg_type == "PING":
                await websocket.send_json({"type": "PONG"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for player {player_name} in room {room_id}")
        if player_name:
            await game_room.remove_player(websocket)

    except Exception as e:
        logger.error(f"WebSocket error in room {room_id}: {e}")
        error = ServerError(
            room=room_id,
            message=str(e),
        )
        try:
            await websocket.send_json(error.model_dump())
        except Exception:
            pass

    finally:
        if websocket in game_room.players:
            await game_room.remove_player(websocket)
