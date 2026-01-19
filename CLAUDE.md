# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
uv sync                    # Install dependencies
uv run fastapi dev         # Start development server (http://localhost:8000, auto-reload)
```

API docs available at `http://localhost:8000/docs` when running.

## Deployment (Railway)

When adding or updating dependencies in `pyproject.toml`, regenerate `requirements.txt`:

```bash
uv export --no-hashes > requirements.txt
```

Railway uses `requirements.txt` for deployment. Dev dependencies (in `[dependency-groups] dev`) are excluded automatically.

## Architecture Overview

FastAPI backend using Supabase for authentication and database. Python 3.12+, managed with UV package manager.

### Key Components

- **`app/main.py`** - FastAPI app entry point, CORS config, router mounting, lifespan hooks for WebSocket/Redis
- **`app/config.py`** - Pydantic Settings loading from `.env`, cached singleton via `@lru_cache`
- **`app/dependencies/auth.py`** - JWT validation using Supabase JWKS, `JWTBearer` security class, `CurrentUser` and `CurrentUserToken` dependencies
- **`app/dependencies/supabase.py`** - Supabase client: `get_supabase_client()` (anon) and `get_authenticated_supabase_client(token)` (with user JWT for RLS)
- **`app/dependencies/redis.py`** - Upstash Redis client singleton: `get_redis_client()` and `close_redis_client()`
- **`app/routers/`** - API route handlers (prefixed with `/api/v1`)
- **`app/routers/ws.py`** - WebSocket endpoint with JWT auth, ping/pong, and room operations
- **`app/schemas/`** - Pydantic models for request/response validation
- **`app/services/websocket/`** - WebSocket infrastructure (auth, connection manager with room subscriptions)
- **`app/services/room/`** - Room service for creating and managing game rooms via Supabase RPC

### Authentication Flow

1. Frontend authenticates via Supabase JS client (signup/signin/OAuth)
2. Frontend sends JWT in `Authorization: Bearer <token>` header
3. `JWTBearer` dependency validates token against Supabase JWKS endpoint
4. `CurrentUser` dependency extracts user info from validated JWT payload
5. Route handlers receive authenticated user data

### Patterns Used

- **Dependency Injection**: FastAPI `Depends()` for auth, settings, clients
- **Singleton Pattern**: `@lru_cache` for settings and anon Supabase client; global instances for Redis and ConnectionManager
- **Router Organization**: Modular endpoints in `app/routers/` with versioned prefixes
- **Authenticated DB Access**: Use `get_authenticated_supabase_client(token)` with `CurrentUserToken` to respect Supabase RLS policies (e.g., `auth.uid() = id`)
- **Lifespan Management**: Async context manager in `main.py` for startup/shutdown of WebSocket manager and Redis

### WebSocket Architecture

- **Endpoint**: `ws://host/api/v1/ws?token=<jwt>` - validates JWT before accepting connection
- **Connection Manager** (`app/services/websocket/manager.py`): Tracks connections locally and in Redis for distributed state, manages room subscriptions
- **Message Protocol**: JSON messages with `type` field:
  - Core: `ping`, `pong`, `connected`, `error`
  - Room: `create_room`, `create_room_ok`, `create_room_error`, `join_room`, `join_room_ok`, `join_room_error`, `room_updated`
- **Redis Keys**:
  - `ws:user:{user_id}:conn_count` - atomic counter for presence tracking
  - `room:{room_id}:meta` - room metadata hash
  - `room:{room_id}:seats` - seat occupancy hash

See `docs/websockets.md` and `docs/redis.md` for detailed documentation.

### Room Operations

**Room Creation** uses a Supabase RPC stored procedure (`create_room`) for atomic operations:
- Idempotency via `ws_idempotency` table (request_id must be UUID)
- Unique 6-character room code generation with collision retry
- Creates room record and 4 seat records in single transaction
- Redis state initialized after successful DB commit (best-effort)

**Room Joining** via WebSocket `join_room` message:
- Accepts `room_code` (not `room_id`) to enforce access control through code knowledge
- Resolves code to room with authorization checks (status, membership)
- Allocates first available seat for new joiners
- Broadcasts `room_updated` to existing room members

### Adding New Features

When implementing major features:
1. Create/update documentation in `docs/` folder
2. Update this file with new components and patterns
3. Update `README.md` with user-facing changes
