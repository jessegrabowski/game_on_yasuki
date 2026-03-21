# Deployment

How to go from local development to a live server that friends can connect to.

## Architecture

```
┌─────────────┐  WebSocket   ┌──────────────────────────┐
│ Tkinter GUI │◄───────────► │  FastAPI  (Railway)       │
│ (local)     │              │    /api/cards    (REST)   │
└─────────────┘              │    /api/rooms    (REST)   │
                             │    /ws/{room}    (WS)     │
┌─────────────┐  HTTP        │           │               │
│ Deck builder│◄───────────► │           ▼               │
│ (browser)   │              │  PostgreSQL (Railway)     │
└─────────────┘              └──────────────────────────┘
                                        │
                             ┌──────────┴──────────┐
                             │  Card images  (R2)  │
                             └─────────────────────┘
```

## Hosting

| Service | Role | Cost |
|---------|------|------|
| [Railway](https://railway.app) (Hobby) | FastAPI + PostgreSQL | ~$5–10/mo |
| [Cloudflare R2](https://www.cloudflare.com/products/r2/) | Card images (8 GB, zero egress) | ~$0.15/mo |
| Cloudflare DNS (optional) | Custom domain | Free |

Railway was chosen over Render (cold starts kill WebSockets) and Fly.io
(more operational complexity for no benefit at this scale).

## Phase 0: Card API + Deck Builder

Deploy what already works — no new code needed.

### Upload images to Cloudflare R2

```bash
brew install rclone

# Create bucket "l5r-images" at https://dash.cloudflare.com → R2
# Enable public access via r2.dev subdomain
# Create an R2 API token (read/write)

rclone config
# Name: r2, Type: s3, Provider: Cloudflare
# Fill in access_key_id, secret_access_key, endpoint

rclone copy sets/ r2:l5r-images/sets/ \
  --progress --transfers=16 \
  --header-upload "Cache-Control: public, max-age=31536000, immutable"
```

### Deploy to Railway

1. Sign up at [railway.app](https://railway.app) with GitHub (Hobby plan, $5/mo)
2. New Project → Deploy from GitHub → select `game-on-yasuki`
3. Add PostgreSQL: click **+ New → Database → PostgreSQL**
4. Set environment variables on the web service:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (auto-linked) |
   | `IMAGE_BASE_URL` | `https://pub-<hash>.r2.dev` |
   | `CORS_ORIGINS` | `https://<app>.up.railway.app` |
   | `SETUPTOOLS_SCM_PRETEND_VERSION` | `0.1.0` |

5. Railway builds the Dockerfile and starts the API. The entrypoint seeds the
   database automatically on first boot.

**Result:** A live URL serving the card API and deck builder. Auto-deploys on
`git push`.

## Phase 1: Tkinter Connects to Remote API

Add a `--server` flag to `play.py` so the desktop client uses the hosted API
instead of a local database.

- New module: an HTTP client wrapping the same interface as `yasuki_core.database`
  but calling `GET /api/cards` instead of running SQL
- Image cache: download card images from R2 on first access, serve from
  `~/.yasuki/image_cache/` thereafter
- No `--server` flag = local mode (works offline)

## Phase 2: Multiplayer Game Rooms

Wire the existing WebSocket infrastructure (`yasuki_web.websocket`,
`yasuki_web.rooms`, `yasuki_web.schemas`) to the actual game engine.

- Replace the placeholder game state dict in `GameRoom` with real `Zone`, `Deck`,
  `Player` objects from `yasuki_core`
- Expand the `Action` schema to cover all game actions (bow, flip, move, draw, etc.)
- GUI sends actions over WebSocket instead of mutating local state directly

```
Today:    GUI ──mutates──► local game state
Goal:     GUI ──action──► server ──validates──► broadcasts ──► all GUIs
```

## What to Defer

- **Authentication** — room passwords are enough for friends-only play
- **Game history / stats** — just database tables, easy to add later
- **Web frontend** — the Tkinter client and browser deck builder are sufficient
- **Scaling** — a single Railway instance handles dozens of concurrent rooms
