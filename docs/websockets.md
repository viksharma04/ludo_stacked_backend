# WebSocket Implementation

Real-time WebSocket infrastructure for Ludo Stacked, enabling live game updates, player presence, and instant notifications.

## Overview

The WebSocket system provides:
- Authenticated persistent connections using Supabase JWTs
- Room-scoped connections (users must have a seat in the room)
- Distributed connection state via Upstash Redis
- Automatic heartbeat/keepalive mechanism
- Room state synchronization with `room_updated` broadcasts
- Ready state management and disconnect handling

## Architecture

```
┌─────────────┐  WS + JWT + room_code   ┌─────────────────┐
│   Client    │ ──────────────────────── │  FastAPI Server │
└─────────────┘                          └────────┬────────┘
                                                  │
                                         ┌────────┴────────┐
                                         │                 │
                                    ┌────▼────┐     ┌──────▼──────┐
                                    │  Local  │     │   Upstash   │
                                    │  State  │     │    Redis    │
                                    └─────────┘     └─────────────┘
```

### Components

| Component | File | Description |
|-----------|------|-------------|
| WebSocket Router | `app/routers/ws.py` | Endpoint handler, room validation, message loop |
| Connection Manager | `app/services/websocket/manager.py` | Local + Redis state, room subscriptions |
| WS Authenticator | `app/services/websocket/auth.py` | JWT validation for WebSocket |
| Room Service | `app/services/room/service.py` | Room state management, ready/leave logic |
| Message Schemas | `app/schemas/ws.py` | Pydantic models for messages |
| Handler Registry | `app/services/websocket/handlers/__init__.py` | Handler registration and dispatch |
| Handler Base | `app/services/websocket/handlers/base.py` | HandlerContext, HandlerResult, helpers |
| Authenticate Handler | `app/services/websocket/handlers/authenticate.py` | AUTHENTICATE handler |
| Ping Handler | `app/services/websocket/handlers/ping.py` | PING/PONG keepalive |
| Ready Handler | `app/services/websocket/handlers/ready.py` | TOGGLE_READY handler |
| Leave Handler | `app/services/websocket/handlers/leave.py` | LEAVE_ROOM handler |
| Redis Client | `app/dependencies/redis.py` | Upstash Redis singleton |

## Connection Flow

The WebSocket connection uses a secure message-based authentication flow. The JWT token is sent after the connection is established, avoiding exposure in URLs, browser history, or server logs.

```
1. Client connects: ws://host/api/v1/ws (no query params needed)
2. Server accepts connection immediately (unauthenticated state)
3. Server starts 30-second auth timeout
4. Client sends: {"type": "authenticate", "payload": {"token": "<JWT>", "room_code": "ABC123"}}
5. Server validates JWT against Supabase JWKS
6. If invalid → sends error response (AUTH_FAILED or AUTH_EXPIRED)
7. Server validates room access (room exists, user has seat)
8. If room invalid → sends error response (ROOM_NOT_FOUND or ROOM_ACCESS_DENIED)
9. If valid → update seat connected=true, mark connection authenticated
10. Server sends: {"type": "authenticated", "payload": {connection_id, user_id, server_id, room}}
11. Server broadcasts: {"type": "room_updated", ...} to other room members
12. Client can now send game messages (ping, toggle_ready, leave_room)
13. Client sends periodic ping, server responds with pong
14. On disconnect → update seat connected=false, reset ready state, broadcast room_updated

Note: If client doesn't send authenticate message within 30 seconds, connection is closed
with code 4005 (AUTH_TIMEOUT).
```

## Message Protocol

**Note:** All messages use a consistent structure with `type`, optional `request_id`, and optional `payload` fields. The `request_id` should be a UUID and is echoed back in responses for request correlation.

### Client → Server

**Authenticate (required first message after connection)**
```json
{
  "type": "authenticate",
  "payload": {
    "token": "eyJhbGciOiJIUzI1NiIs...",
    "room_code": "ABC123"
  }
}
```

**Ping (keepalive)**
```json
{
  "type": "ping",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Toggle Ready**
```json
{
  "type": "toggle_ready",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Leave Room**
```json
{
  "type": "leave_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Server → Client

**Authenticated (on successful authentication)**
```json
{
  "type": "authenticated",
  "payload": {
    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-uuid",
    "server_id": "server-1",
    "room": {
      "room_id": "room-uuid",
      "code": "ABC123",
      "status": "open",
      "visibility": "private",
      "ruleset_id": "classic",
      "max_players": 4,
      "seats": [
        {
          "seat_index": 0,
          "user_id": "user-uuid",
          "display_name": "Player 1",
          "ready": "not_ready",
          "connected": true,
          "is_host": true
        }
      ],
      "version": 1
    }
  }
}
```

**Connected (legacy, for pre-authenticated connections)**
```json
{
  "type": "connected",
  "payload": {
    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-uuid",
    "server_id": "server-1",
    "room": { ... }
  }
}
```

**Pong (response to ping)**
```json
{
  "type": "pong",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "server_time": "2024-01-15T10:30:00Z"
  }
}
```

**Room Updated (broadcast on state changes)**
```json
{
  "type": "room_updated",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_id": "room-uuid",
    "code": "ABC123",
    "status": "ready_to_start",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [...],
    "version": 2
  }
}
```

**Room Closed (when host leaves)**
```json
{
  "type": "room_closed",
  "payload": {
    "reason": "host_left",
    "room_id": "room-uuid"
  }
}
```

**Error**
```json
{
  "type": "error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "error_code": "INVALID_MESSAGE",
    "message": "Invalid message format"
  }
}
```

## Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `authenticate` | Client → Server | Authenticate connection with JWT and room code |
| `authenticated` | Server → Client | Authentication succeeded with room snapshot |
| `ping` | Client → Server | Keepalive request (allowed before auth) |
| `pong` | Server → Client | Keepalive response |
| `connected` | Server → Client | Connection acknowledgment (legacy flow) |
| `toggle_ready` | Client → Server | Toggle user's ready state (requires auth) |
| `leave_room` | Client → Server | Leave the current room (requires auth) |
| `room_updated` | Server → Client | Room state changed (broadcast) |
| `room_closed` | Server → Client | Room was closed by host |
| `error` | Server → Client | Error notification |

## Room State

### Seat Snapshot

Each seat in a room has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `seat_index` | int | Seat position (0 to max_players-1) |
| `user_id` | string \| null | User occupying the seat, or null if empty |
| `display_name` | string \| null | User's display name |
| `ready` | string | Ready state: `"not_ready"` or `"ready"` |
| `connected` | bool | Whether user has active WebSocket connection |
| `is_host` | bool | Whether this seat is the room host |

### Room Status

| Status | Description |
|--------|-------------|
| `open` | Accepting players, not all ready |
| `ready_to_start` | All players ready (min 2), can start game |
| `in_game` | Game in progress |
| `closed` | Room closed (host left or game ended) |

## Close Codes

| Code | Name | Description |
|------|------|-------------|
| 1000 | NORMAL | Normal closure |
| 1001 | GOING_AWAY | Server shutdown or client navigating away |
| 1007 | INVALID_DATA | Invalid message format |
| 4001 | AUTH_FAILED | JWT validation failed |
| 4002 | AUTH_EXPIRED | JWT has expired |
| 4003 | ROOM_NOT_FOUND | Room code doesn't exist or room is closed |
| 4004 | ROOM_ACCESS_DENIED | User doesn't have a seat in the room |
| 4005 | AUTH_TIMEOUT | Client didn't send authenticate message within 30 seconds |

## Redis State

Redis stores room state and presence tracking.

### Keys

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `ws:user:{user_id}:conn_count` | Integer | Atomic connection counter for a user |
| `room:{room_id}:meta` | Hash | Room metadata (status, visibility, max_players, etc.) |
| `room:{room_id}:seats` | Hash | Seat data (seat:0, seat:1, etc.) |

Connection details and heartbeats are tracked locally per server. Redis uses atomic `INCR`/`DECR` operations on connection counters to safely track presence across multi-server deployments. When a user's count reaches 0, the key is deleted.

## Configuration

Environment variables in `.env`:

```env
# Upstash Redis (required)
UPSTASH_REDIS_REST_URL=https://xxx.upstash.io
UPSTASH_REDIS_REST_TOKEN=xxx

# WebSocket settings (optional, shown with defaults)
WS_HEARTBEAT_INTERVAL=30    # Cleanup check interval in seconds
WS_CONNECTION_TIMEOUT=60    # Max seconds without heartbeat before disconnect
```

## Usage Examples

### JavaScript Client

```javascript
const token = await supabase.auth.getSession().data.session.access_token;
const roomCode = 'ABC123';

// Connect without credentials in URL (more secure)
const ws = new WebSocket('ws://localhost:8000/api/v1/ws');

ws.onopen = () => {
  console.log('Connected, sending authentication...');

  // Send authentication message with token and room code
  ws.send(JSON.stringify({
    type: 'authenticate',
    payload: {
      token: token,
      room_code: roomCode
    }
  }));
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);

  if (message.type === 'authenticated') {
    // Store room state
    const room = message.payload.room;
    console.log('Authenticated! Room:', room.code, 'Status:', room.status);

    // Start heartbeat
    setInterval(() => {
      ws.send(JSON.stringify({ type: 'ping' }));
    }, 25000);
  }

  if (message.type === 'error') {
    console.error('Error:', message.payload.error_code, message.payload.message);
    // Handle auth errors
    if (['AUTH_FAILED', 'AUTH_EXPIRED', 'ROOM_NOT_FOUND', 'ROOM_ACCESS_DENIED'].includes(message.payload.error_code)) {
      ws.close();
    }
  }

  if (message.type === 'room_updated') {
    // Update local room state
    const room = message.payload;
    console.log('Room updated:', room.status, 'Version:', room.version);
  }

  if (message.type === 'room_closed') {
    console.log('Room closed:', message.payload.reason);
    ws.close();
  }
};

// Toggle ready state
function toggleReady() {
  ws.send(JSON.stringify({
    type: 'toggle_ready',
    request_id: crypto.randomUUID()
  }));
}

// Leave room
function leaveRoom() {
  ws.send(JSON.stringify({
    type: 'leave_room',
    request_id: crypto.randomUUID()
  }));
}

ws.onclose = (event) => {
  console.log('Disconnected:', event.code, event.reason);
};
```

### wscat (CLI testing)

```bash
# Install wscat
npm install -g wscat

# Connect (no credentials needed in URL)
wscat -c "ws://localhost:8000/api/v1/ws"

# Authenticate with token and room code
> {"type": "authenticate", "payload": {"token": "YOUR_JWT_TOKEN", "room_code": "ABC123"}}
< {"type": "authenticated", "payload": {...}}

# Send ping
> {"type": "ping"}
< {"type": "pong", ...}

# Toggle ready
> {"type": "toggle_ready", "request_id": "test-123"}
< {"type": "room_updated", ...}

# Leave room
> {"type": "leave_room", "request_id": "test-456"}
< {"type": "room_updated", ...}
```

## Connection Manager API

The `ConnectionManager` class provides methods for managing connections:

```python
from app.services.websocket.manager import get_connection_manager

manager = get_connection_manager()

# Connect (called internally by ws router)
connection = await manager.connect(websocket, user_id, room_id, room_snapshot)

# Check if user is online (across all servers)
is_online = await manager.is_user_online(user_id)

# Send message to specific connection
await manager.send_to_connection(connection_id, message)

# Send message to all connections of a user (on this server)
count = await manager.send_to_user(user_id, message)

# Broadcast to all connections (on this server)
count = await manager.broadcast(message)

# Get connection info
connection = manager.get_connection(connection_id)
total = manager.get_total_connection_count()
user_count = manager.get_user_connection_count(user_id)

# Room messaging (connections auto-subscribed on connect)
count = await manager.send_to_room(room_id, message, exclude_connection=None)
await manager.unsubscribe_from_room(connection_id)
```

## Handler Architecture

The WebSocket system uses a handler/dispatcher pattern for processing messages. This provides a clean separation of concerns and makes it easy to add new message types.

### Core Components

**HandlerContext** - Context passed to each handler:
```python
@dataclass
class HandlerContext:
    connection_id: str           # Unique connection identifier
    user_id: str                 # Authenticated user ID
    message: WSClientMessage     # The incoming message
    manager: ConnectionManager   # For sending responses/broadcasts
```

**HandlerResult** - Result returned by handlers:
```python
@dataclass
class HandlerResult:
    success: bool                           # Whether handling succeeded
    response: WSServerMessage | None        # Direct response to sender
    broadcast: WSServerMessage | None       # Message to broadcast to room
    room_id: str | None                     # Target room for broadcast
```

### Helper Functions

The `base.py` module provides helper functions for handlers:

```python
from app.services.websocket.handlers.base import (
    error_response,
    require_authenticated,
    validate_request_id,
    validate_payload,
    snapshot_to_pydantic,
)

# Require authentication (use at start of handlers that need auth)
auth_error = require_authenticated(ctx)
if auth_error:
    return auth_error

# Create an error response
result = error_response(
    error_code="NOT_IN_ROOM",
    message="You are not in a room",
    error_type=MessageType.ERROR,
    request_id=ctx.message.request_id,
)

# Validate request_id is present and valid UUID
error = validate_request_id(ctx.message.request_id, MessageType.ERROR)
if error:
    return error

# Validate payload against a schema
payload, error = validate_payload(
    ctx.message.payload, MyPayloadSchema, ctx.message.request_id, MessageType.ERROR
)
if error:
    return error

# Convert RoomSnapshotData to Pydantic RoomSnapshot
pydantic_snapshot = snapshot_to_pydantic(room_snapshot_data)
```

### Handler Registration

Handlers are registered via the `@handler` decorator:
```python
from app.services.websocket.handlers import handler
from app.services.websocket.handlers.base import HandlerContext, HandlerResult

@handler(MessageType.PING)
async def handle_ping(ctx: HandlerContext) -> HandlerResult:
    return HandlerResult(
        success=True,
        response=WSServerMessage(type=MessageType.PONG, ...)
    )
```

### Message Dispatch

The `dispatch()` function routes incoming messages to registered handlers:
1. Receives a `HandlerContext` with the message and connection info
2. Looks up the handler for the message type
3. Calls the handler and returns its `HandlerResult`
4. Returns `None` if no handler is registered for the message type

The router then:
- Sends `result.response` to the requesting connection
- Broadcasts `result.broadcast` to `result.room_id` (excluding sender)

## Extending the Protocol

To add new message types:

1. Add type to `MessageType` enum in `app/schemas/ws.py`
2. Create payload schema if needed in `app/schemas/ws.py`
3. Create a new handler file in `app/services/websocket/handlers/`
4. Import the handler in `app/services/websocket/handlers/__init__.py`

Example:
```python
# In app/schemas/ws.py
class MessageType(str, Enum):
    PING = "ping"
    PONG = "pong"
    CONNECTED = "connected"
    ERROR = "error"
    ROOM_UPDATED = "room_updated"
    TOGGLE_READY = "toggle_ready"
    LEAVE_ROOM = "leave_room"
    ROOM_CLOSED = "room_closed"
    START_GAME = "start_game"  # New type

# In app/services/websocket/handlers/start_game.py
from app.schemas.ws import MessageType, WSServerMessage
from app.services.websocket.handlers import handler
from app.services.websocket.handlers.base import (
    HandlerContext,
    HandlerResult,
    error_response,
    require_authenticated,
    snapshot_to_pydantic,
)

@handler(MessageType.START_GAME)
async def handle_start_game(ctx: HandlerContext) -> HandlerResult:
    # Require authentication (all game handlers should check this)
    auth_error = require_authenticated(ctx)
    if auth_error:
        return auth_error

    # Get room from connection
    connection = ctx.manager.get_connection(ctx.connection_id)
    if not connection or not connection.room_id:
        return error_response(
            error_code="NOT_IN_ROOM",
            message="You are not in a room",
            error_type=MessageType.ERROR,
            request_id=ctx.message.request_id,
        )

    room_id = connection.room_id
    # ... validate host, room status, start game logic ...

    return HandlerResult(
        success=True,
        response=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            request_id=ctx.message.request_id,
            payload=snapshot.model_dump(),
        ),
        broadcast=WSServerMessage(
            type=MessageType.ROOM_UPDATED,
            payload=snapshot.model_dump(),
        ),
        room_id=room_id,
    )

# In app/services/websocket/handlers/__init__.py
from . import authenticate, leave, ping, ready, start_game  # Add new import
```
