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
│   └── ws.py            # WebSocket endpoint
├── schemas/
│   ├── auth.py          # Auth request/response models
│   ├── profile.py       # Profile request/response models
│   └── ws.py            # WebSocket message models
└── services/
    ├── room/
    │   └── service.py   # Room creation via Supabase RPC
    └── websocket/
        ├── auth.py      # WebSocket JWT validation
        └── manager.py   # Connection state manager
docs/
├── redis.md             # Redis integration guide
└── websockets.md        # WebSocket implementation guide
specs/
├── room_creation_feature.md      # Backend room creation spec
└── frontend_room_creation.md     # Frontend room creation spec
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

### WebSocket (`/api/v1/ws`)

| Endpoint | Description | Auth |
|----------|-------------|------|
| `ws://host/api/v1/ws?token=<jwt>` | Real-time connection | JWT in query param |

**Supported Message Types:**

| Type | Direction | Description |
|------|-----------|-------------|
| `ping` / `pong` | Client ↔ Server | Keepalive heartbeat |
| `connected` | Server → Client | Connection acknowledgment |
| `create_room` | Client → Server | Create a new game room |
| `create_room_ok` | Server → Client | Room created successfully |
| `create_room_error` | Server → Client | Room creation failed |

See [docs/websockets.md](docs/websockets.md) for protocol details.

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

## Learn More

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Supabase Auth Documentation](https://supabase.com/docs/guides/auth)
- [Supabase JWT Signing Keys](https://supabase.com/docs/guides/auth/signing-keys)
