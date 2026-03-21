# FastAPI Backend

## Quick Start

### 1. Start the Server

```bash
# Development mode with auto-reload
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

# Or with logging
uvicorn app.api.main:app --reload --log-level debug
```

Server will start at http://localhost:8000

### 2. View API Documentation

Open your browser to:
- **Interactive docs:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

### 3. Test the API

```bash
# Run HTTP endpoint tests
python app/api/test_api.py

# Run WebSocket tests
python app/api/test_websocket.py
```

## API Endpoints

### Cards

- `GET /api/cards` - List all cards with filtering
  - Query params: `search`, `deck`, `clan`, `card_type`, `limit`, `offset`
- `GET /api/cards/{card_id}` - Get specific card details
- `GET /api/cards/random/{count}` - Get random cards
- `GET /api/sets` - List all card sets
- `GET /api/formats` - List game formats
- `GET /api/decks` - List deck types

### Game Rooms

- `POST /api/rooms` - Create a new game room
- `GET /api/rooms` - List available rooms
- `GET /api/rooms/{room_id}` - Get room details
- `DELETE /api/rooms/{room_id}` - Delete a room
- `GET /api/rooms/{room_id}/players` - List players in room

### WebSocket

- `WS /ws/{room_id}` - Real-time game communication

## WebSocket Protocol

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
    "player_states": {...}
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

## Examples

### Create a Room and Play

```bash
# Create room
curl -X POST http://localhost:8000/api/rooms \
  -H "Content-Type: application/json" \
  -d '{"room_name": "My Game", "max_players": 2}'

# Response includes room_id
# {"room_id": "abc123", ...}

# Connect via WebSocket (use browser or Python)
# ws://localhost:8000/ws/abc123
```

### Search for Cards

```bash
# Search by name/text
curl "http://localhost:8000/api/cards?search=dragon&limit=10"

# Filter by deck type
curl "http://localhost:8000/api/cards?deck=dynasty&clan=dragon"
```

### Get Random Cards

```bash
# Get 5 random cards
curl http://localhost:8000/api/cards/random/5

# Get random cards from specific deck
curl "http://localhost:8000/api/cards/random/10?deck=fate"
```

## Development

### Adding New Endpoints

1. Create or edit files in `app/api/`
2. Add router to `app/api/main.py`
3. Define request/response schemas in `app/schemas.py`
4. Server auto-reloads when files change

### Integrating Game Engine

The WebSocket handler (`app/api/websocket.py`) currently has placeholder logic. Integrate your game engine:

```python
from app.engine.players import Player, PlayerId
from app.game_pieces.deck import Deck

class GameRoom:
    def __init__(self, room_id: str):
        self.room_id = room_id
        # Use your actual game engine
        self.player1 = Player(PlayerId.P1)
        self.player2 = Player(PlayerId.P2)
        # Initialize zones, decks, etc.

    async def handle_action(self, ws: WebSocket, action: dict):
        # Validate action with game rules
        # Update game state
        # Broadcast to players
        pass
```

## Deployment

### Railway

```bash
railway login
railway init
railway up
```

### Fly.io

```bash
fly launch
fly deploy
```

### Docker

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install -e .

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t game-yasuki-api .
docker run -p 8000:8000 game-yasuki-api
```

## Environment Variables

- `L5R_DATABASE_URL` - PostgreSQL connection string
- `PORT` - Server port (default: 8000)

## CORS Configuration

Current CORS allows connections from:
- http://localhost:5173 (Vite dev server)
- http://localhost:3000 (React dev server)
- http://localhost:8080 (Vue dev server)

Update `app/api/main.py` to add production domain when deploying.

## Next Steps

1. **Test locally** - Run server and test scripts
2. **Build frontend** - Create web UI that consumes this API
3. **Integrate game engine** - Replace placeholder logic with actual game rules
4. **Deploy** - Push to Railway/Fly.io
5. **Share** - Give URL to friends to test multiplayer

## Troubleshooting

**Database connection errors:**
- Ensure PostgreSQL is running
- Check `L5R_DATABASE_URL` environment variable
- Run database initialization: `python -m app.install.install_db`

**CORS errors in browser:**
- Add your frontend URL to `allow_origins` in `main.py`

**WebSocket disconnects:**
- Check firewall/proxy settings
- Ensure server supports WebSocket upgrades

**Port already in use:**
- Change port: `uvicorn app.api.main:app --port 8001`
