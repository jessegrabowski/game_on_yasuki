from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import logging
import random
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from pydantic import ValidationError

from yasuki_web import auth
from yasuki_web.config import allowed_origins
from yasuki_web.schemas import (
    ClientMessage,
    IntentEnvelope,
    intent_from_envelope,
    ServerHello,
    ServerSnapshot,
    ServerError,
    ServerChat,
    ServerLog,
    ServerDeckContents,
)
from yasuki_web.snapshot import serialize_snapshot, serialize_deck_cards
from yasuki_web.game_log import describe_intent
from yasuki_web.rooms import rooms

from yasuki_core.engine.players import PlayerId
from yasuki_core.engine.table import (
    TableState,
    Intent,
    IntentOp,
    Event,
    SearchDeck,
)
from yasuki_core.engine.action_log import (
    ActionLog,
    InitialRecord,
    ChatEntry,
    SessionEntry,
    apply_and_log,
)
from yasuki_core.engine.redaction import redact
from yasuki_core.engine.setup import setup_seat, flip_second_player_stronghold
from yasuki_core.game_pieces.factory import resolve_decklist
from yasuki_core.decklist import parse_deck_yaml
from yasuki_core.database import get_cards_by_names

logger = logging.getLogger(__name__)
router = APIRouter()

connections: dict[str, set[WebSocket]] = {}
ip_connections: dict[str, int] = {}
MAX_CONNECTIONS_PER_IP = 5
HISTORY_LIMIT = 200

# parse_deck_yaml's placeholder when the export carries no `name:` line; treated as "unnamed" so the
# client-supplied filename can stand in.
_DEFAULT_DECK_NAME = "Imported Deck"
# Final fallback label when a deck has neither a name nor a client filename.
_UNNAMED_DECK_LABEL = "a deck"


def _deck_display_name(parsed: dict, filename: str | None) -> str:
    """Pick the label for a loaded deck: the parsed deck name, else the client filename, else a
    generic fallback."""
    name = (parsed.get("name") or "").strip()
    if name and name != _DEFAULT_DECK_NAME:
        return name
    return (filename or "").strip() or _UNNAMED_DECK_LABEL


def _entry_names(entry: dict):
    """The card names a decklist entry references: its own, plus its art-swap donor's when present."""
    yield entry["name"]
    if entry.get("art"):
        yield entry["art"]["name"]


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
        # The authenticated identity behind each connection, and the seat each user holds. Seating
        # binds to user_id, not to a connection, so a player's second tab attaches to their existing
        # seat instead of consuming another one.
        self.user_by_ws: dict[WebSocket, int] = {}
        self.seat_by_user: dict[int, PlayerId] = {}
        self.state = TableState.empty_two_seat()
        self.action_log = ActionLog(initial=InitialRecord.from_state(self.state))
        self._spawn_count = 0
        # Parsed decklists awaiting setup, keyed by seat.
        self.pending_decks: dict[PlayerId, dict] = {}
        self.setup_done = False
        # Seats that have voted for a new game; the table clears once every seated player has.
        self.reset_votes: set[PlayerId] = set()
        # Chat and log persist for the room's lifetime so a player who joins (or rejoins) sees what
        # came before. Capped to the most recent HISTORY_LIMIT of each.
        self.chat_history: list[dict] = []
        self.log_history: list[dict] = []

    def _free_seat(self) -> PlayerId | None:
        return next((s for s in PlayerId if s not in self.seats.values()), None)

    async def add_player(self, ws: WebSocket, user: dict):
        """Seat a joining player (P1/P2), replay the room's chat and log history, and announce them.

        Seating binds to ``user["id"]``: a player already holding a seat (a second tab) attaches the
        new connection to that seat and is brought up to date privately, rather than taking another
        seat or re-announcing a join. A genuinely new player with no free seat (a backstop behind
        the room's max-players cap) is told the table is full and left unseated.
        """
        user_id = user["id"]
        name = user["display_name"]
        seat = self.seat_by_user.get(user_id)
        rejoining = seat is not None

        if seat is None:
            seat = self._free_seat()
            if seat is None:
                msg = ServerError(room=self.room_id, message="Table is full")
                await ws.send_json(msg.model_dump())
                return
            self.seat_by_user[user_id] = seat
            self.state.seats[seat].name = name
            self.state.seats[seat].avatar = user.get("avatar")
            self.state.seats[seat].connected = True
            self.state.bump_version()
            rooms[self.room_id]["players"].append(name)

        self.seats[ws] = seat
        self.players[ws] = name
        self.user_by_ws[ws] = user_id

        hello = ServerHello(
            room=self.room_id,
            you=name,
            your_seat=seat.name,
            # A player's multiple tabs repeat one name; dedup so the roster lists each player once.
            players=list(dict.fromkeys(self.players.values())),
            seq=self.state.seq,
        )
        await ws.send_json(hello.model_dump())

        for entry in self.log_history:
            await ws.send_json(entry)
        for entry in self.chat_history:
            await ws.send_json(entry)

        logger.info(f"Player {name} took seat {seat.name} in room {self.room_id}")

        if rejoining:
            # The seat, roster, and tape are unchanged; only this new tab needs the current view.
            await self._send_snapshot(ws, seat)
            return

        self.action_log.append(SessionEntry(ts=time.time(), seat=seat, name=name, event="join"))
        await self.broadcast_snapshots()
        await self.log([{"text": f"{name} joined"}])

    async def remove_player(self, ws: WebSocket):
        """Drop one connection, freeing its seat and announcing the departure only when it was the
        player's last tab — another open tab keeps the seat live for an uninterrupted game."""
        seat = self.seats.pop(ws, None)
        player_name = self.players.pop(ws, None)
        user_id = self.user_by_ws.pop(ws, None)
        # A surviving connection on the same seat means the player still has another tab open.
        seat_vacated = seat is not None and seat not in self.seats.values()
        if not seat_vacated:
            return

        self.state.seats[seat].connected = False
        self.state.bump_version()
        self.reset_votes.discard(seat)
        self.seat_by_user.pop(user_id, None)

        if player_name:
            if self.room_id in rooms and player_name in rooms[self.room_id]["players"]:
                rooms[self.room_id]["players"].remove(player_name)
            logger.info(f"Player {player_name} left room {self.room_id}")
            self.action_log.append(
                SessionEntry(ts=time.time(), seat=seat, name=player_name, event="leave")
            )
            await self.broadcast_snapshots()
            await self.log([{"text": f"{player_name} left"}])

    async def handle_intent(self, ws: WebSocket, envelope: IntentEnvelope):
        """Apply one intent for the acting seat through the authoritative core, record it, and
        broadcast. A malformed or unauthorized intent is rejected with `ERROR`, state unchanged."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        if envelope.op is IntentOp.SPAWN_CARD and not envelope.card_id:
            # The server mints spawn ids so a replay reproduces the same card; the client never sends
            # one.
            self._spawn_count += 1
            envelope = envelope.model_copy(update={"card_id": f"spawn-{self._spawn_count}"})
        try:
            intent = intent_from_envelope(envelope)
        except (KeyError, ValueError, TypeError):
            await ws.send_json(
                ServerError(room=self.room_id, message="Invalid intent", debug=True).model_dump()
            )
            return

        events = apply_and_log(self.state, self.action_log, seat, intent, ts=time.time())
        if not events:
            await ws.send_json(
                ServerError(room=self.room_id, message="Intent rejected", debug=True).model_dump()
            )
            # Re-send the authoritative view so any optimistic local change the client made for this
            # move (a hidden drag source, a card nudged to its drop point) snaps back.
            await self._send_snapshot(ws, seat)
            return
        await self.broadcast_snapshots()
        await self._log_intent(seat, intent, events[0])
        if isinstance(intent, SearchDeck):
            await self._send_deck_contents(ws, intent)

    async def _send_deck_contents(self, ws: WebSocket, intent: SearchDeck):
        """Deliver the searched deck's ordered cards to the requesting owner alone.

        The intent is owner-gated upstream (``_search_deck`` rejects a non-owner before this runs),
        so the deck named by ``intent.deck`` belongs to the player on ``ws``. The cards go only to
        ``ws`` — never broadcast — so deck order stays private to its owner.
        """
        deck = self.state.decks.get(intent.deck)
        if deck is None:
            return
        # A bounded search reveals only the top N cards (stored top-last), not the whole deck.
        cards = deck.cards
        if intent.limit is not None and intent.limit > 0:
            cards = cards[-intent.limit :]
        message = ServerDeckContents(
            room=self.room_id,
            deck={"owner": intent.deck.owner.name, "side": intent.deck.side.value},
            cards=serialize_deck_cards(cards),
        )
        await ws.send_json(message.model_dump())

    async def handle_load_deck(self, ws: WebSocket, yaml_text: str, filename: str | None = None):
        """Parse a deck-builder export YAML for the acting seat, stash its dynasty/fate/pre-game
        name lists for setup, and announce the load. A decklist that yields no recognizable cards
        is rejected with `ERROR` and nothing is stashed."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        parsed = parse_deck_yaml(yaml_text)
        if not (parsed["pre_game"] or parsed["dynasty"] or parsed["fate"]):
            await ws.send_json(
                ServerError(
                    room=self.room_id, message="Deck has no recognizable cards"
                ).model_dump()
            )
            return
        self.pending_decks[seat] = parsed
        deck_name = _deck_display_name(parsed, filename)
        await self.log([{"text": f"{self.players[ws]} loaded "}, {"text": deck_name}])

    async def handle_ready(self, ws: WebSocket, ready: bool, solo: bool = False):
        """Set the acting seat's ready flag and deal the opening table once everyone seated is ready.

        Readying requires a loaded deck. A normal ready waits for both seats; `solo` deals a
        one-seat goldfish table for the lone player. Setup runs at most once — start a fresh game
        with `RESET`."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        if ready and seat not in self.pending_decks:
            await ws.send_json(
                ServerError(room=self.room_id, message="Load a deck before readying").model_dump()
            )
            return
        self.state.seats[seat].ready = ready
        self.state.bump_version()
        self.action_log.append(
            SessionEntry(
                ts=time.time(),
                seat=seat,
                name=self.state.seats[seat].name,
                event="ready" if ready else "unready",
            )
        )
        if ready and not self.setup_done and self._ready_to_deal(solo):
            await self._run_setup()
            self.setup_done = True
        await self.broadcast_snapshots()

    def _ready_to_deal(self, solo: bool) -> bool:
        """Both seats ready, or one ready player who opted to goldfish solo."""
        seated = list(self.seats.values())
        if not seated or not all(self.state.seats[seat].ready for seat in seated):
            return False
        return len(seated) == len(PlayerId) or solo

    async def handle_reset(self, ws: WebSocket):
        """Record the acting seat's vote for a new game. The table clears only once every seated
        player has agreed — a lone goldfisher's vote is unanimous on its own — keeping seats and
        loaded decks so players can ready up again immediately."""
        seat = self.seats.get(ws)
        if seat is None:
            return
        self.reset_votes.add(seat)
        if self.reset_votes >= set(self.seats.values()):
            self._clear_table()
            self.reset_votes.clear()
            await self.broadcast_snapshots()
            await self.log([{"text": "A new game begins"}])
        else:
            await self.log([{"text": f"{self.players[ws]} wants a new game"}])

    def _clear_table(self):
        names = {seat: info.name for seat, info in self.state.seats.items()}
        prev_seq = self.state.seq
        self.state = TableState.empty_two_seat(names[PlayerId.P1], names[PlayerId.P2])
        # Carry the view version across the reset so seq stays strictly increasing for the room's
        # life; a client never sees it go backwards on a new game.
        self.state.seq = prev_seq + 1
        for seat in self.seats.values():
            self.state.seats[seat].connected = True
        self.action_log = ActionLog(initial=InitialRecord.from_state(self.state))
        self.setup_done = False

    async def _run_setup(self):
        """Resolve both seats' decks and deal the opening table, then re-seed the action log so the
        post-setup state is the replay head."""
        # Fetch the recipients and any art-swap donors (a borrowed printing's card may not otherwise
        # be in either deck), so the resolver can recomposite custom art.
        names = sorted(
            {
                name
                for parsed in self.pending_decks.values()
                for section in ("pre_game", "dynasty", "fate")
                for entry in parsed[section]
                for name in _entry_names(entry)
            }
        )
        records = await asyncio.to_thread(get_cards_by_names, names)
        for seat, parsed in self.pending_decks.items():
            resolved = resolve_decklist(parsed, records, seat)
            setup_seat(
                self.state,
                seat,
                resolved,
                dynasty_seed=random.getrandbits(31),
                fate_seed=random.getrandbits(31),
            )
        # In a two-player game the lower-honor seat goes second, its stronghold flipped to its back
        # face (when it has one). A goldfish/solo table (one seat) and an honor tie leave both
        # fronts.
        seats = tuple(self.pending_decks)
        if len(seats) == 2:
            flip_second_player_stronghold(self.state, seats)
        self.action_log = ActionLog(initial=InitialRecord.from_state(self.state))

    async def _send_snapshot(self, ws: WebSocket, seat: PlayerId):
        """Send one seated player its own redacted `SNAPSHOT`."""
        view = serialize_snapshot(redact(self.state, seat))
        await ws.send_json(ServerSnapshot(room=self.room_id, snapshot=view).model_dump())

    async def broadcast_snapshots(self):
        """Send each seated player its own redacted `SNAPSHOT`. This is the per-viewer leak fix:
        the opponent's hand and face-down cards are stubs in the bytes that reach the wrong client."""
        disconnected = []
        for ws, seat in list(self.seats.items()):
            try:
                await self._send_snapshot(ws, seat)
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

    async def log(self, parts: list[dict]):
        """Store and broadcast a game-log line (text and card-link segments) to the whole room."""
        payload = ServerLog(room=self.room_id, parts=parts).model_dump()
        self._append_capped(self.log_history, payload)
        await self._broadcast(payload)

    async def _log_intent(self, seat: PlayerId, intent: Intent, event: Event):
        """Append a human-readable game-log line for an accepted intent, unless it is one not shown
        (card repositioning)."""
        parts = describe_intent(self.state, self.state.seats[seat].name, intent, event)
        if parts:
            await self.log(parts)


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


# Sized for the largest legitimate frame, a LOAD_DECK carrying a full decklist YAML (~3-4 KiB of
# content, capped at 16 KiB by LoadDeckRequest). Realtime intents are tiny; the token-bucket
# throttle below — not this per-frame cap — is what bounds a flood.
MAX_WS_MESSAGE_SIZE = 32768

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


async def _authenticate(websocket: WebSocket) -> dict | None:
    """The authenticated account behind the handshake, or None."""
    return await auth.user_for_websocket(websocket)


@router.websocket("/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    if not _origin_allowed(websocket):
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    # Play is login-required: an anonymous handshake (no valid session cookie) is refused.
    user = await _authenticate(websocket)
    if user is None:
        await websocket.close(code=4401, reason="Authentication required")
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
                # Identity comes from the authenticated account, not the client frame; the JOIN name
                # is vestigial and ignored.
                player_name = user["display_name"]
                await game_room.add_player(websocket, user)

            elif message.type == "INTENT":
                if message.intent is not None:
                    await game_room.handle_intent(websocket, message.intent)

            elif message.type == "CHAT":
                if message.chat is not None:
                    await game_room.handle_chat(websocket, message.chat.text)

            elif message.type == "LOAD_DECK":
                if message.load_deck is not None:
                    await game_room.handle_load_deck(
                        websocket, message.load_deck.yaml, message.load_deck.filename
                    )

            elif message.type == "READY":
                if message.ready is not None:
                    await game_room.handle_ready(websocket, message.ready.ready, message.ready.solo)

            elif message.type == "RESET":
                await game_room.handle_reset(websocket)

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
