# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
uv sync                    # Install dependencies
uv run fastapi dev         # Start development server (http://localhost:8000, auto-reload)
uv run pytest              # Run tests
uv run pytest -v           # Run tests with verbose output
uv run ruff check          # Lint code
uv run ruff format         # Format code
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
- **`app/routers/`** - API route handlers (prefixed with `/api/v1`): `auth.py`, `profile.py`, `rooms.py`, `ws.py`
- **`app/routers/ws.py`** - WebSocket endpoint with JWT auth, ping/pong, and room operations
- **`app/schemas/`** - Pydantic models for request/response validation
- **`app/services/websocket/`** - WebSocket infrastructure (auth, connection manager with room subscriptions)
- **`app/services/room/`** - Room service for creating and managing game rooms via Supabase RPC
- **`app/services/game/`** - Game initialization and engine
- **`app/utils/`** - Utility modules (e.g., `board_render.py` for board visualization)

### Game Engine (`app/services/game/engine/`)

The game engine handles all Ludo Stacked game mechanics:

- **`actions.py`** - Player action models (RollAction, MoveAction, CaptureChoiceAction, StartGameAction)
- **`events.py`** - Game event models broadcast via WebSocket (14 event types)
- **`process.py`** - Main entry point `process_action()` - validates and processes actions
- **`validation.py`** - Pre-processing validation (phase, turn, legal moves)
- **`rolling.py`** - Dice roll processing, extra rolls, three-sixes penalty
- **`movement.py`** - Stack movement, collision detection (road and homestretch)
- **`legal_moves.py`** - Calculate valid moves after dice roll
- **`captures.py`** - Collision resolution, capture mechanics
- **`stack_utils.py`** - Composition-based stack ID utilities (merge, split, naming conventions)

Related: **`app/services/game/start_game.py`** - Game initialization, creates initial stacks and board setup.

### Board Geometry (grid_length = g)

- `step = 2g + 1` (distance between starting positions; 13 for g=6)
- `starting_positions = [0, step, 2*step, 3*step]` (always 4 positions on board)
- `squares_to_homestretch = 8g + 2` (ROAD: progress 0 to sth-1; HOMESTRETCH: sth to stw-1)
- `squares_to_win = 9g + 1` (HEAVEN at exactly this progress)
- `homestretch_length = g - 1`
- `safe_offset = 2g - 5` from each starting position
- Board is always complete regardless of player count (all 4 starts, all 8 safe spaces)
- 2 players: opposite corners (1st and 3rd starting positions)
- 3 players: first three starting positions

**Absolute position formula** (for collision tests): `abs_pos = (player.abs_starting_index + progress) % squares_to_homestretch`. When setting up test collisions, solve for the opponent's `progress` given a target `abs_pos`.

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
- **Multi-roll allocation**: `AwaitingChoice` presents all accumulated rolls with legal moves via `RollMoveGroup`; player specifies `roll_value` in `MoveAction`

### WebSocket Architecture

- **Endpoint**: `ws://host/api/v1/ws` - accepts connection immediately, requires authentication message
- **Authentication**: Secure message-based auth (token not exposed in URL):
  1. Client connects to `ws://host/api/v1/ws`
  2. Client sends: `{"type": "authenticate", "payload": {"token": "<jwt>", "room_code": "ABC123"}}`
  3. Server validates and responds with `authenticated` or `error`
  4. 30-second timeout for authentication
- **Connection Manager** (`app/services/websocket/manager.py`): Tracks connections locally and in Redis for distributed state, manages room subscriptions
- **Handler Pattern** (`app/services/websocket/handlers/`): `base.py` provides decorator-based handler registration, use `require_authenticated()` for auth-required handlers
- **Message Protocol**: JSON messages with `type` field:
  - Auth: `authenticate`, `authenticated`
  - Core: `ping`, `pong`, `connected`, `error`
  - Room: `toggle_ready`, `leave_room`, `room_updated`, `room_closed`
  - Game: `start_game`, `game_started`, `game_action`, `game_events`, `game_state`, `game_error`
- **Redis Keys**:
  - `ws:user:{user_id}:conn_count` - atomic counter for presence tracking
  - `room:{room_id}:meta` - room metadata hash
  - `room:{room_id}:seats` - seat occupancy hash

See `docs/websockets.md`, `docs/redis.md`, and `docs/db_schema.md` for detailed documentation. Design documents live in `docs/plans/`.

### Room Operations

Room creation uses a Supabase RPC stored procedure (`find_or_create_room`) for atomic operations:
- Idempotency via `ws_idempotency` table (request_id must be UUID)
- Unique 6-character room code generation with collision retry
- Creates room record and 4 seat records in single transaction
- Redis state initialized after successful DB commit (best-effort)

### Testing

Tests live in `tests/` and cover the game engine exclusively. Run with `uv run pytest`.

- **`conftest.py`** - Shared fixtures: fixed player UUIDs, standard/two-player board setups, helper state builders
- Test files map to engine modules: `test_movement.py`, `test_rolling.py`, `test_captures.py`, `test_validation.py`, `test_stack_utils.py`, `test_stacking.py`, `test_events.py`, `test_game_finished.py`, `test_get_out_of_hell.py`, `test_start_game_handler.py`, `test_board_geometry.py`, `test_homestretch_heaven.py`, `test_hell_exit_collisions.py`, `test_multi_roll_allocation.py`, `test_capture_chains.py`, `test_capture_choice.py`, `test_full_turn_flow.py`
- Tests construct `GameState` directly and call engine functions — no HTTP/WebSocket integration tests yet
- All tests currently pass. When new game rules are added, failing tests may be used as the implementation backlog. See `docs/plans/2026-02-28-core-engine-test-suite-design.md` for design details.
- **Board fixtures use grid_length=6**: `squares_to_win=55`, `squares_to_homestretch=50`, `safe_spaces=[0,7,13,20,26,33,39,46]`

### Known Implementation Gaps

- `_create_board_setup()`: `squares_to_homestretch` uses `8g+1` instead of `8g+2`; 2-player uses consecutive starts instead of opposite corners
- HELL exit doesn't trigger collision detection (no merge with own stack at starting position)

### Adding New Features

When implementing major features:
1. Create/update documentation in `docs/` folder
2. Update this file with new components and patterns
3. Update `README.md` with user-facing changes
