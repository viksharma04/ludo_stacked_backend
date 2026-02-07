# Ludo Stacked Backend

Backend for the Ludo Stacked game. Ludo Stacked is a variation of the popular game known as Ludo or Pachisi. The game introduces new fun rules that take strategy to the next level and increase the importance of each player decision.

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Supabase project with authentication enabled
- [Upstash Redis](https://upstash.com/) database (for WebSocket state)

### Environment Setup

Create a `.env` file with the following variables:

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_API_KEY=your-anon-key

# Google OAuth (if using)
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret

# Upstash Redis (for WebSocket state)
UPSTASH_REDIS_REST_URL=https://your-instance.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token

# App config
CORS_ORIGINS=["http://localhost:3000"]
DEBUG=true
```

### Install Dependencies

```bash
uv sync
```

### Start the Development Server

```bash
uv run fastapi dev
```

Visit http://localhost:8000

API docs available at http://localhost:8000/docs

## Project Structure

```
app/
├── __init__.py
├── main.py              # FastAPI application entry point
├── config.py            # Environment configuration
├── dependencies/
│   ├── auth.py          # JWT validation via Supabase JWKS
│   ├── redis.py         # Upstash Redis client
│   └── supabase.py      # Supabase client (anon + authenticated)
├── routers/
│   ├── auth.py          # Authentication endpoints
│   ├── profile.py       # User profile endpoints
│   ├── rooms.py         # Room management endpoints
│   └── ws.py            # WebSocket endpoint
├── schemas/
│   ├── auth.py          # Auth request/response models
│   ├── profile.py       # Profile request/response models
│   ├── room.py          # Room request/response models
│   ├── ws.py            # WebSocket message models
│   └── game_engine.py   # Game state models
├── services/
│   ├── game/
│   │   ├── start_game.py    # Game initialization
│   │   └── engine/          # Core game logic
│   │       ├── actions.py   # Player action models
│   │       ├── events.py    # Game event models
│   │       ├── process.py   # Action processing entry point
│   │       ├── validation.py # Action validation
│   │       ├── rolling.py   # Dice roll processing
│   │       ├── movement.py  # Token/stack movement
│   │       ├── legal_moves.py # Legal move calculation
│   │       └── captures.py  # Collision & capture resolution
│   ├── room/
│   │   └── service.py   # Room management service
│   └── websocket/
│       ├── auth.py      # WebSocket JWT validation
│       ├── manager.py   # Connection state manager
│       └── handlers/    # Message handlers
│           ├── authenticate.py  # Authentication handler
│           ├── ping.py          # Ping/pong keepalive
│           ├── ready.py         # Toggle ready state
│           ├── leave.py         # Leave room handler
│           ├── start_game.py    # Start game handler
│           └── game.py          # Game action handler
└── utils/
    └── board_renderer.py  # Board visualization utilities
docs/
├── redis.md                     # Redis integration guide
├── websockets.md                # WebSocket implementation guide
├── db_schema.md                 # Database schema reference
├── game_engine.md               # Game engine architecture
├── frontend_integration.md      # Frontend integration guide
├── frontend_roll_granted.md     # Roll granted event details
├── frontend_start_game.md       # Start game flow
└── frontend_stack_split_changes.md  # Stack split mechanics
tests/
└── test_stacking.py     # Game mechanics unit tests
```

## API Endpoints

### Authentication (`/api/v1/auth`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/me` | Get current user info from JWT | Yes |

### Profile (`/api/v1/profile`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/v1/profile` | Get current user's profile | Yes |
| PATCH | `/api/v1/profile` | Update display name (1-50 chars) | Yes |

### Rooms (`/api/v1/rooms`)

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/v1/rooms` | Create a new room (or return existing) | Yes |
| POST | `/api/v1/rooms/join` | Join an existing room by code | Yes |

**Create Room Request:**
```json
{ "n_players": 4 }
```

**Create Room Response:**
```json
{
  "room_id": "uuid",
  "code": "ABC123",
  "seat": { "seat_index": 0, "is_host": true },
  "cached": false
}
```

**Join Room Request:**
```json
{ "code": "ABC123" }
```

**Join Room Response:**
```json
{
  "room_id": "uuid",
  "code": "ABC123",
  "seat": { "seat_index": 1, "is_host": false }
}
```

### WebSocket (`/api/v1/ws`)

| Endpoint | Description | Auth |
|----------|-------------|------|
| `ws://host/api/v1/ws` | Real-time room connection | Message-based |

**Connection Flow:**
1. Connect to `ws://host/api/v1/ws` (no query params needed)
2. Send authentication message: `{"type": "authenticate", "payload": {"token": "<jwt>", "room_code": "ABC123"}}`
3. Receive `authenticated` response with room snapshot
4. Client can now send game messages

**Supported Message Types:**

| Type | Direction | Description |
|------|-----------|-------------|
| `authenticate` | Client → Server | Authenticate with JWT and room code |
| `authenticated` | Server → Client | Authentication success with room snapshot |
| `ping` / `pong` | Client ↔ Server | Keepalive heartbeat |
| `toggle_ready` | Client → Server | Toggle ready state |
| `leave_room` | Client → Server | Leave the current room |
| `room_updated` | Server → Client | Room state changed |
| `room_closed` | Server → Client | Room closed (host left) |
| `start_game` | Client → Server | Host starts the game |
| `game_started` | Server → Client | Game has begun (host only) |
| `game_action` | Client → Server | Player game action (roll, move, etc.) |
| `game_events` | Server → Client | Game events broadcast |
| `game_error` | Server → Client | Game action error |
| `error` | Server → Client | General error notification |

See [docs/websockets.md](docs/websockets.md) for full protocol details.

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | API info |
| GET | `/health` | Health check |

## Authentication

This backend validates JWTs issued by Supabase via JWKS. All authentication flows (signup, signin, OAuth, token refresh) are handled by the frontend using the Supabase JS client.

### Auth Flow

```
Frontend                              Backend
   |                                     |
   |-- supabase.auth.signUp() ------->  (Supabase handles)
   |-- supabase.auth.signInWithPassword() --> (Supabase handles)
   |-- supabase.auth.signInWithOAuth() --> (Supabase handles)
   |                                     |
   |-- GET /api/v1/auth/me -----------> | Validates JWT via JWKS
   |   Authorization: Bearer <jwt>      | Returns user profile
   |<-- { id, email } ----------------- |
   |                                     |
   |-- GET /api/v1/games -------------> | Validates JWT
   |   Authorization: Bearer <jwt>      | Uses user for game logic
   |<-- [...games...] ---------------- |
```

### Using Protected Endpoints

Include the access token in the Authorization header:

```bash
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## Supabase Configuration

### Required Settings

1. **JWT Signing Keys**: Ensure RS256 keys are active (default for new projects)
2. **Email Provider**: Configure in Supabase dashboard (for email/password auth)
3. **OAuth Providers**: Configure in Supabase dashboard (for social logins)

## Game Engine

The game engine (`app/services/game/engine/`) implements Ludo Stacked game mechanics:

- **Token States**: HELL → ROAD → HOMESTRETCH → HEAVEN
- **Dice Rolling**: Roll 1-6, extra roll on 6, three sixes penalty
- **Stacking**: Own tokens on same position stack together, move as unit with effective roll = roll / stack height
- **Captures**: Landing on opponent token sends it to HELL, grants bonus roll
- **Safe Spaces**: Starting positions and marked spaces where tokens cannot be captured

See [docs/game_engine.md](docs/game_engine.md) for detailed architecture documentation.

## Learn More

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Supabase JWT Signing Keys](https://supabase.com/docs/guides/auth/signing-keys)
