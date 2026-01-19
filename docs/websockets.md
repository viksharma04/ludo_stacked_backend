# WebSocket Implementation

Real-time WebSocket infrastructure for Ludo Stacked, enabling live game updates, player presence, and instant notifications.

## Overview

The WebSocket system provides:
- Authenticated persistent connections using Supabase JWTs
- Distributed connection state via Upstash Redis
- Automatic heartbeat/keepalive mechanism
- Graceful connection cleanup

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
| Redis Client | `app/dependencies/redis.py` | Upstash Redis singleton |

## Connection Flow

```
1. Client connects: ws://host/api/v1/ws?token=<JWT>
2. Server validates JWT against Supabase JWKS (before accepting)
3. If invalid → close with code 4001 (AUTH_FAILED) or 4002 (AUTH_EXPIRED)
4. If valid → accept connection, register in local + Redis state
5. Server sends: {"type": "connected", "payload": {"connection_id": "...", "user_id": "...", "server_id": "..."}}
6. Client sends periodic ping, server responds with pong
7. On disconnect → cleanup from local + Redis state
```

## Message Protocol

### Client → Server

**Ping (keepalive)**
```json
{
  "type": "ping",
  "timestamp": "2024-01-15T10:30:00Z",
  "request_id": "abc123"
}
```

### Server → Client

**Connected (on successful connection)**
```json
{
  "type": "connected",
  "timestamp": "2024-01-15T10:30:00Z",
  "payload": {
    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "user-uuid",
    "server_id": "server-1"
  }
}
```

**Pong (response to ping)**
```json
{
  "type": "pong",
  "timestamp": "2024-01-15T10:30:00Z",
  "request_id": "abc123",
  "payload": {
    "server_time": "2024-01-15T10:30:00Z"
  }
}
```

**Error**
```json
{
  "type": "error",
  "timestamp": "2024-01-15T10:30:00Z",
  "error": "Invalid message format",
  "code": 1007
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
```json
{
  "type": "create_room_ok",
  "timestamp": "2024-01-15T10:30:00Z",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "AB12CD",
    "seat_index": 0,
    "is_host": true
  }
}
```

**Server → Client: `create_room_error`**
```json
{
  "type": "create_room_error",
  "timestamp": "2024-01-15T10:30:00Z",
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

## Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `ping` | Client → Server | Keepalive request |
| `pong` | Server → Client | Keepalive response |
| `connected` | Server → Client | Connection acknowledgment |
| `error` | Server → Client | Error notification |
| `create_room` | Client → Server | Create a new game room |
| `create_room_ok` | Server → Client | Room creation succeeded |
| `create_room_error` | Server → Client | Room creation failed |

## Close Codes

| Code | Name | Description |
|------|------|-------------|
| 1000 | NORMAL | Normal closure |
| 1001 | GOING_AWAY | Server shutdown or client navigating away |
| 1007 | INVALID_DATA | Invalid message format |
| 4001 | AUTH_FAILED | JWT validation failed |
| 4002 | AUTH_EXPIRED | JWT has expired |

## Redis State

Redis stores minimal state for user presence tracking using atomic counters.

### Keys

| Key Pattern | Type | Description |
|-------------|------|-------------|
| `ws:user:{user_id}:conn_count` | Integer | Atomic connection counter for a user |

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
};

ws.onclose = (event) => {
  console.log('Disconnected:', event.code, event.reason);
};
```

### wscat (CLI testing)

```bash
# Install wscat
npm install -g wscat

# Connect with token
wscat -c "ws://localhost:8000/api/v1/ws?token=YOUR_JWT_TOKEN"

# Send ping
> {"type": "ping"}
< {"type": "pong", ...}
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
2. Create payload schema if needed
3. Add handler in `app/routers/ws.py` message loop

Example:
```python
# In app/schemas/ws.py
class MessageType(str, Enum):
    PING = "ping"
    PONG = "pong"
    CONNECTED = "connected"
    ERROR = "error"
    GAME_UPDATE = "game_update"  # New type

# In app/routers/ws.py
if message.type == MessageType.GAME_UPDATE:
    # Handle game update
    pass
```
