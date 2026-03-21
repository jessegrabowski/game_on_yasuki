# API Reference

## REST Endpoints

### Cards

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/cards` | List/search cards (supports Scryfall-style syntax) |
| `GET` | `/api/cards/{card_id}` | Get card details with all print variations |
| `GET` | `/api/cards/random/{count}` | Get random cards |
| `GET` | `/api/sets` | List all card sets |
| `GET` | `/api/formats` | List game formats in chronological order |
| `GET` | `/api/decks` | List deck types (Dynasty, Fate) |
| `GET` | `/api/clans` | List all clans |
| `GET` | `/api/card-types` | List all card types |

### Game Rooms

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/rooms` | Create a new game room |
| `GET` | `/api/rooms` | List available (waiting, not full) rooms |
| `GET` | `/api/rooms/{room_id}` | Get room details |
| `DELETE` | `/api/rooms/{room_id}?token=...` | Delete a room (requires delete token) |
| `GET` | `/api/rooms/{room_id}/players` | List players in a room |

### Other

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | API info and version |
| `GET` | `/health` | Health check |
| `GET` | `/api/config` | Client configuration (image base URL) |

## WebSocket Protocol

Connect to `WS /ws/{room_id}` for real-time game communication.

### Flow

1. Client creates a room via `POST /api/rooms` (receives `room_id` and `delete_token`)
2. Client connects to `/ws/{room_id}`
3. Client sends a `JOIN` message with player name
4. Server responds with `HELLO` containing room info
5. Clients exchange `ACTION` messages
6. Server broadcasts `STATE` updates to all players

### Client → Server Messages

**Join Room:**
```json
{
  "type": "JOIN",
  "room": "room-id",
  "join": {
    "name": "PlayerName"
  }
}
```

**Send Action:**
```json
{
  "type": "ACTION",
  "room": "room-id",
  "action": {
    "kind": "PLAY_CARD",
    "card": "card-id"
  }
}
```

**Ping (keepalive):**
```json
{
  "type": "PING"
}
```

### Server → Client Messages

**Hello (on join):**
```json
{
  "type": "HELLO",
  "room": "room-id",
  "you": "PlayerName",
  "players": ["Player1", "Player2"],
  "seq": 0
}
```

**State Update:**
```json
{
  "type": "STATE",
  "room": "room-id",
  "seq": 1,
  "state": {
    "turn": 0,
    "phase": "setup",
    "player_states": {}
  }
}
```

**Error:**
```json
{
  "type": "ERROR",
  "room": "room-id",
  "message": "Error description"
}
```

### Close Codes

| Code | Meaning |
|------|---------|
| `1009` | Message too large (>4 KB) |
| `4003` | Room full |
| `4004` | Room not found |
| `4029` | Too many connections from this IP |

### Action Kinds

| Kind | Fields | Description |
|------|--------|-------------|
| `PLAY_CARD` | `card` | Play a card by ID |
| `DRAW` | — | Draw a card |
| `PASS` | — | Pass (advances turn) |
| `SHUFFLE` | `deck_type` | Shuffle a deck (`dynasty` or `fate`) |

Message schemas are defined in `src/yasuki_web/schemas.py`.
