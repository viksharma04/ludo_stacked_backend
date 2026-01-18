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

- **`app/main.py`** - FastAPI app entry point, CORS config, router mounting, health endpoint
- **`app/config.py`** - Pydantic Settings loading from `.env`, cached singleton via `@lru_cache`
- **`app/dependencies/auth.py`** - JWT validation using Supabase JWKS, `JWTBearer` security class, `CurrentUser` and `CurrentUserToken` dependencies
- **`app/dependencies/supabase.py`** - Supabase client: `get_supabase_client()` (anon) and `get_authenticated_supabase_client(token)` (with user JWT for RLS)
- **`app/routers/`** - API route handlers (prefixed with `/api/v1`)
- **`app/schemas/`** - Pydantic models for request/response validation

### Authentication Flow

1. Frontend authenticates via Supabase JS client (signup/signin/OAuth)
2. Frontend sends JWT in `Authorization: Bearer <token>` header
3. `JWTBearer` dependency validates token against Supabase JWKS endpoint
4. `CurrentUser` dependency extracts user info from validated JWT payload
5. Route handlers receive authenticated user data

### Patterns Used

- **Dependency Injection**: FastAPI `Depends()` for auth, settings, clients
- **Singleton Pattern**: `@lru_cache` for settings and anon Supabase client
- **Router Organization**: Modular endpoints in `app/routers/` with versioned prefixes
- **Authenticated DB Access**: Use `get_authenticated_supabase_client(token)` with `CurrentUserToken` to respect Supabase RLS policies (e.g., `auth.uid() = id`)
