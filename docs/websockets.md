# WebSocket Implementation

Real-time WebSocket infrastructure for Ludo Stacked, enabling live game updates, player presence, and instant notifications.

## Overview

The WebSocket system provides:
- Authenticated persistent connections using Supabase JWTs
- Distributed connection state via Upstash Redis
- Automatic heartbeat/keepalive mechanism
- Graceful connection cleanup
- Room-based messaging and broadcasts

## Architecture

```
┌─────────────┐     WebSocket + JWT      ┌─────────────────┐
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
| WebSocket Router | `app/routers/ws.py` | Endpoint handler, message loop |
| Connection Manager | `app/services/websocket/manager.py` | Local + Redis state management |
| WS Authenticator | `app/services/websocket/auth.py` | JWT validation for WebSocket |
| Message Schemas | `app/schemas/ws.py` | Pydantic models for messages |
| Room Service | `app/services/room/service.py` | Room creation, joining, state |
| Redis Client | `app/dependencies/redis.py` | Upstash Redis singleton |

## Connection Flow

```
1. Client connects: ws://host/api/v1/ws?token=<JWT>
2. Server validates JWT against Supabase JWKS (before accepting)
3. If invalid → close with code 4001 (AUTH_FAILED) or 4002 (AUTH_EXPIRED)
4. If valid → accept connection, register in local + Redis state
5. Server sends: {"type": "connected", "payload": {...}}
6. Client sends periodic ping, server responds with pong
7. On disconnect → cleanup from local + Redis state
```

## Message Protocol

All messages follow a consistent structure:

**Client → Server:**
```json
{
  "type": "message_type",
  "request_id": "optional-uuid-for-request-response",
  "payload": { ... }
}
```

**Server → Client:**
```json
{
  "type": "message_type",
  "request_id": "echoed-from-request-if-applicable",
  "payload": { ... }
}
```

## Core Messages

### Ping/Pong (Keepalive)

**Client → Server: `ping`**
```json
{
  "type": "ping",
  "request_id": "abc123"
}
```

**Server → Client: `pong`**
```json
{
  "type": "pong",
  "request_id": "abc123",
  "payload": {
    "server_time": "2024-01-15T10:30:00Z"
  }
}
```

### Connected

Sent immediately after successful connection:

**Server → Client: `connected`**
```json
{
  "type": "connected",
  "payload": {
    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-uuid",
    "server_id": "server-1"
  }
}
```

### Error

Generic error for protocol-level issues (e.g., invalid message format):

**Server → Client: `error`**
```json
{
  "type": "error",
  "payload": {
    "error_code": "INVALID_MESSAGE",
    "message": "Invalid message format"
  }
}
```

## Room Operations

### Create Room

**Client → Server: `create_room`**
```json
{
  "type": "create_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "visibility": "private",
    "max_players": 4,
    "ruleset_id": "classic",
    "ruleset_config": {}
  }
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `request_id` | UUID | Yes | Must be valid UUID v4 (for idempotency) |
| `visibility` | string | Yes | Must be `"private"` |
| `max_players` | number | No | 2-4, default: 4 |
| `ruleset_id` | string | Yes | Must be `"classic"` |
| `ruleset_config` | object | No | Default: `{}` |

**Server → Client: `create_room_ok`**

Returns a `RoomSnapshot` directly as payload:
```json
{
  "type": "create_room_ok",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "AB12CD",
    "status": "open",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [
      {
        "seat_index": 0,
        "user_id": "creator-user-id",
        "display_name": "PlayerName",
        "ready": "not_ready",
        "connected": true,
        "is_host": true
      },
      { "seat_index": 1, "user_id": null, "display_name": null, "ready": "not_ready", "connected": false, "is_host": false },
      { "seat_index": 2, "user_id": null, "display_name": null, "ready": "not_ready", "connected": false, "is_host": false },
      { "seat_index": 3, "user_id": null, "display_name": null, "ready": "not_ready", "connected": false, "is_host": false }
    ],
    "version": 0
  }
}
```

**Server → Client: `create_room_error`**
```json
{
  "type": "create_room_error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "error_code": "VALIDATION_ERROR",
    "message": "request_id must be a valid UUID"
  }
}
```

| Error Code | Description |
|------------|-------------|
| `VALIDATION_ERROR` | Invalid payload or request_id |
| `REQUEST_IN_PROGRESS` | Same request_id already being processed |
| `CODE_GENERATION_FAILED` | Could not generate unique room code |
| `INTERNAL_ERROR` | Unexpected server error |

### Join Room

**Client → Server: `join_room`**
```json
{
  "type": "join_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_code": "AB12CD"
  }
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `request_id` | UUID | Yes | Must be valid UUID v4 |
| `room_code` | string | Yes | 6 characters, A-Z and 0-9 only |

**Server → Client: `join_room_ok`**

Returns a `RoomSnapshot` directly as payload:
```json
{
  "type": "join_room_ok",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "AB12CD",
    "status": "open",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [...],
    "version": 1
  }
}
```

**Server → Client: `join_room_error`**
```json
{
  "type": "join_room_error",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "error_code": "ROOM_NOT_FOUND",
    "message": "Room not found"
  }
}
```

| Error Code | Description |
|------------|-------------|
| `VALIDATION_ERROR` | Invalid request_id or room_code format |
| `ROOM_NOT_FOUND` | Invalid code or room doesn't exist |
| `ROOM_CLOSED` | Room no longer joinable |
| `ROOM_IN_GAME` | Room in game and user not a member |
| `ROOM_FULL` | No available seats |
| `INTERNAL_ERROR` | Unexpected server error |

### Room Updated (Broadcast)

Sent to all room members when room state changes (e.g., player joins):

**Server → Client: `room_updated`**
```json
{
  "type": "room_updated",
  "payload": {
    "room_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "AB12CD",
    "status": "open",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [...],
    "version": 2
  }
}
```

## Payload Schemas

### RoomSnapshot

Used as payload for `create_room_ok`, `join_room_ok`, and `room_updated`:

| Field | Type | Description |
|-------|------|-------------|
| `room_id` | string | UUID of the room |
| `code` | string | 6-character join code |
| `status` | string | `open`, `in_game`, or `closed` |
| `visibility` | string | `private` |
| `ruleset_id` | string | Game ruleset identifier |
| `max_players` | number | 2-4 |
| `seats` | array | List of SeatSnapshot objects |
| `version` | number | Optimistic locking version |

### SeatSnapshot

| Field | Type | Description |
|-------|------|-------------|
| `seat_index` | number | 0-3 |
| `user_id` | string/null | User ID if occupied |
| `display_name` | string/null | Player display name |
| `ready` | string | `not_ready` or `ready` |
| `connected` | boolean | Whether player is connected |
| `is_host` | boolean | Whether this seat is the host |

### ErrorPayload

Used for all error messages (`error`, `create_room_error`, `join_room_error`):

| Field | Type | Description |
|-------|------|-------------|
| `error_code` | string | Machine-readable error code |
| `message` | string | Human-readable description |

## Message Types Summary

| Type | Direction | Description |
|------|-----------|-------------|
| `ping` | Client → Server | Keepalive request |
| `pong` | Server → Client | Keepalive response |
| `connected` | Server → Client | Connection acknowledgment |
| `error` | Server → Client | Protocol-level error |
| `create_room` | Client → Server | Create a new game room |
| `create_room_ok` | Server → Client | Room creation succeeded |
| `create_room_error` | Server → Client | Room creation failed |
| `join_room` | Client → Server | Join an existing room |
| `join_room_ok` | Server → Client | Room join succeeded |
| `join_room_error` | Server → Client | Room join failed |
| `room_updated` | Server → Client | Room state changed (broadcast) |

## Close Codes

| Code | Name | Description |
|------|------|-------------|
| 1000 | NORMAL | Normal closure |
| 1001 | GOING_AWAY | Server shutdown or client navigating away |
| 1007 | INVALID_DATA | Invalid message format |
| 4001 | AUTH_FAILED | JWT validation failed |
| 4002 | AUTH_EXPIRED | JWT has expired |

## Redis State

Redis stores state for user presence and room data.

### Keys

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `ws:user:{user_id}:conn_count` | Integer | Connection counter per user |
| `room:{room_id}:meta` | Hash | Room metadata |
| `room:{room_id}:seats` | Hash | Seat occupancy data |
| `room:{room_id}:presence` | Set | Connected user IDs (TTL: 300s) |

See `docs/redis.md` for detailed Redis schema documentation.

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
const ws = new WebSocket(`ws://localhost:8000/api/v1/ws?token=${token}`);

ws.onopen = () => {
  console.log('Connected');
};

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log('Received:', message);

  if (message.type === 'connected') {
    // Start heartbeat
    setInterval(() => {
      ws.send(JSON.stringify({ type: 'ping' }));
    }, 25000);
  }

  if (message.type === 'create_room_ok') {
    const room = message.payload; // RoomSnapshot
    console.log('Room created:', room.code);
  }

  if (message.type === 'join_room_ok') {
    const room = message.payload; // RoomSnapshot
    console.log('Joined room:', room.code);
  }

  if (message.type === 'room_updated') {
    const room = message.payload; // RoomSnapshot
    console.log('Room updated:', room);
  }
};

// Create a room
ws.send(JSON.stringify({
  type: 'create_room',
  request_id: crypto.randomUUID(),
  payload: {
    visibility: 'private',
    max_players: 4,
    ruleset_id: 'classic',
    ruleset_config: {}
  }
}));

// Join a room
ws.send(JSON.stringify({
  type: 'join_room',
  request_id: crypto.randomUUID(),
  payload: {
    room_code: 'AB12CD'
  }
}));
```

### wscat (CLI testing)

```bash
# Install wscat
npm install -g wscat

# Connect with token
wscat -c "ws://localhost:8000/api/v1/ws?token=YOUR_JWT_TOKEN"

# Send ping
> {"type": "ping"}
< {"type": "pong", "payload": {"server_time": "..."}}

# Create room
> {"type": "create_room", "request_id": "550e8400-e29b-41d4-a716-446655440000", "payload": {"visibility": "private", "max_players": 4, "ruleset_id": "classic"}}

# Join room
> {"type": "join_room", "request_id": "660e8400-e29b-41d4-a716-446655440001", "payload": {"room_code": "AB12CD"}}
```

## Connection Manager API

The `ConnectionManager` class provides methods for managing connections:

```python
from app.services.websocket.manager import get_connection_manager

manager = get_connection_manager()

# Check if user is online (across all servers)
is_online = await manager.is_user_online(user_id)

# Send message to specific connection
await manager.send_to_connection(connection_id, message)

# Send message to all connections of a user (on this server)
count = await manager.send_to_user(user_id, message)

# Broadcast to all connections (on this server)
count = await manager.broadcast(message)

# Get connection count
total = manager.get_total_connection_count()
user_count = manager.get_user_connection_count(user_id)

# Room subscriptions
await manager.subscribe_to_room(connection_id, room_id)
await manager.unsubscribe_from_room(connection_id)
count = await manager.send_to_room(room_id, message, exclude_connection=None)
```

## Extending the Protocol

To add new message types:

1. Add type to `MessageType` enum in `app/schemas/ws.py`
2. Create payload schema if needed (or reuse `ErrorPayload`, `RoomSnapshot`)
3. Add handler in `app/routers/ws.py` message loop

Example:
```python
# In app/schemas/ws.py
class MessageType(str, Enum):
    # ... existing types ...
    LEAVE_ROOM = "leave_room"
    LEAVE_ROOM_OK = "leave_room_ok"

# In app/routers/ws.py
elif message.type == MessageType.LEAVE_ROOM:
    # Handle leave room
    pass
```
