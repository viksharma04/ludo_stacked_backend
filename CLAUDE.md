# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
uv sync                    # Install dependencies
uv run fastapi dev         # Start development server (http://localhost:8000, auto-reload)
```

API docs available at `http://localhost:8000/docs` when running.

## Architecture Overview

FastAPI backend using Supabase for authentication and database. Python 3.12+, managed with UV package manager.

### Key Components

- **`app/main.py`** - FastAPI app entry point, CORS config, router mounting, lifespan hooks for WebSocket/Redis
- **`app/config.py`** - Pydantic Settings loading from `.env`, cached singleton via `@lru_cache`
- **`app/dependencies/auth.py`** - JWT validation using Supabase JWKS, `JWTBearer` security class, `CurrentUser` and `CurrentUserToken` dependencies
- **`app/dependencies/supabase.py`** - Supabase client: `get_supabase_client()` (anon) and `get_authenticated_supabase_client(token)` (with user JWT for RLS)
- **`app/dependencies/redis.py`** - Upstash Redis client singleton: `get_redis_client()` and `close_redis_client()`
- **`app/routers/`** - API route handlers (prefixed with `/api/v1`)
- **`app/routers/ws.py`** - WebSocket endpoint with JWT auth and ping/pong handling
- **`app/schemas/`** - Pydantic models for request/response validation
- **`app/services/websocket/`** - WebSocket infrastructure (auth, connection manager)

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
- **Connection Manager** (`app/services/websocket/manager.py`): Tracks connections locally and in Redis for distributed state
- **Message Protocol**: JSON messages with `type` field (`ping`, `pong`, `connected`, `error`)
- **Redis Keys**: `ws:active_users` (Set of online user IDs)

See `docs/websockets.md` and `docs/redis.md` for detailed documentation.

### Adding New Features

When implementing major features:
1. Create/update documentation in `docs/` folder
2. Update this file with new components and patterns
3. Update `README.md` with user-facing changes
