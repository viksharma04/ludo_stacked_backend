# BACKEND SPEC

## Feature: Join Room by Code (Lobby Entry)

## 1. Purpose

Enable a user to join an existing room lobby using a **short join code**, allocate a seat, establish realtime membership, and receive an **authoritative room snapshot** suitable for lobby rendering.

---

## 2. Functional Responsibilities

The backend must:

* Resolve join codes to rooms with authorization checks
* Enforce room join eligibility (status, capacity)
* Allocate a seat for new joiners
* Register user presence in realtime state
* Bind WebSocket connections to room context
* Deliver a complete, consistent room snapshot
* Broadcast updates to existing room members
* Support concurrent joins safely

---

## 3. Entry Point

### WebSocket: Join Room

**Client → Server: `join_room`**
```json
{
  "type": "join_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_code": "ABC123"
  }
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `request_id` | UUID | Yes | Must be valid UUID v4 |
| `room_code` | string | Yes | 6 characters, A-Z and 0-9 only |

**Server → Client: `join_room_ok`**
```json
{
  "type": "join_room_ok",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "room_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "ABC123",
    "status": "open",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [
      {
        "seat_index": 0,
        "user_id": "host-user-id",
        "display_name": "HostPlayer",
        "ready": "not_ready",
        "connected": true,
        "is_host": true
      },
      {
        "seat_index": 1,
        "user_id": "joining-user-id",
        "display_name": "JoiningPlayer",
        "ready": "not_ready",
        "connected": true,
        "is_host": false
      },
      {
        "seat_index": 2,
        "user_id": null,
        "display_name": null,
        "ready": "not_ready",
        "connected": false,
        "is_host": false
      },
      {
        "seat_index": 3,
        "user_id": null,
        "display_name": null,
        "ready": "not_ready",
        "connected": false,
        "is_host": false
      }
    ],
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

**Server → Other Room Members: `room_updated`**

When a new player joins, all other connected room members receive:
```json
{
  "type": "room_updated",
  "payload": {
    "room_id": "...",
    "code": "ABC123",
    "status": "open",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [...],
    "version": 1
  }
}
```

---

## 4. Room Join Rules

* Room must exist (valid room code)
* Room must be "open" status for new joiners
* Room in "in_game" status allows rejoin only if user already has a seat
* Room must not be "closed"
* Joining **allocates a seat** (first available)
* User already seated gets idempotent rejoin (updates connected status)
* Room must have available seats (not full)

---

## 5. Authorization

**Security**: The WebSocket endpoint accepts `room_code` directly (not `room_id`) to ensure access control is enforced through knowledge of the room code. This prevents unauthorized access by users who might know or guess a `room_id`.

**Resolution Flow**:
1. Client provides `room_code`
2. Server queries database for room by code
3. Server validates room status and user eligibility
4. Server returns `room_id` only in success response

---

## 6. Room Snapshot Contract

### Snapshot Characteristics

* Authoritative - single source of truth
* Replace-all - client discards previous lobby state
* Sufficient to fully render lobby UI

### Snapshot Fields

| Field | Type | Description |
|-------|------|-------------|
| `room_id` | UUID | Unique room identifier |
| `code` | string | 6-character join code |
| `status` | string | Room status: open, in_game, closed |
| `visibility` | string | Room visibility: private |
| `ruleset_id` | string | Game ruleset identifier |
| `max_players` | number | Maximum players (2-4) |
| `seats` | array | List of seat snapshots |
| `version` | number | Optimistic locking version |

### Seat Snapshot Fields

| Field | Type | Description |
|-------|------|-------------|
| `seat_index` | number | Seat position (0-3) |
| `user_id` | string/null | Occupying user's ID |
| `display_name` | string/null | Player display name |
| `ready` | string | Ready status: not_ready, ready |
| `connected` | boolean | Whether player is connected |
| `is_host` | boolean | Whether this seat is the host |

---

## 7. State Management

### Redis Responsibilities

* Track active presence per room (`room:{room_id}:presence`)
* Store live room state (`room:{room_id}:meta`, `room:{room_id}:seats`)
* Provide fast snapshot reads
* Presence TTL for cleanup (300 seconds)

### Database Responsibilities

* Persist room and seat records
* Resolve join codes to room_id
* Serve as lifecycle authority (open/in_game/closed)
* Optimistic locking on seat allocation

---

## 8. Disconnect & Rejoin Handling

* Presence removed on disconnect or via TTL
* Rejoin (same user, same room) triggers:
  * Connected status update (not new seat allocation)
  * Full snapshot delivery
* Backend treats rejoin as idempotent

---

## 9. Error Handling

All errors use the standard error payload format:
```json
{
  "error_code": "ERROR_CODE",
  "message": "Human-readable description"
}
```

| Error Code | HTTP Equivalent | Description |
|------------|-----------------|-------------|
| `VALIDATION_ERROR` | 400 | Invalid request_id or room_code format |
| `ROOM_NOT_FOUND` | 404 | Invalid code or room doesn't exist |
| `ROOM_CLOSED` | 410 | Room no longer joinable |
| `ROOM_IN_GAME` | 403 | Room in game and user not a member |
| `ROOM_FULL` | 409 | No available seats |
| `INTERNAL_ERROR` | 500 | Unexpected failure |

---

## 10. Observability

### Logging

* Join attempts with user_id, room_code, connection_id
* Join successes with room_id, seat_index
* Join failures with error_code and reason
* Room update broadcasts

### Metrics (Future)

* Join latency
* Failed join rate by error_code
* Active users per room

---

## 11. Implementation Details

### Files

| File | Purpose |
|------|---------|
| `app/schemas/ws.py` | `JoinRoomPayload`, `RoomSnapshot`, `ErrorPayload` |
| `app/services/room/service.py` | `join_room()`, `_resolve_room_code()` |
| `app/routers/ws.py` | WebSocket handler for `JOIN_ROOM` |

### Join Flow

1. Validate `request_id` is valid UUID
2. Validate `room_code` format (6 chars, A-Z0-9)
3. Resolve room code to room_id via `_resolve_room_code()`
4. Get room snapshot from Redis
5. Check if user already seated (idempotent rejoin)
6. Find first empty seat
7. Update database (optimistic lock on empty seat)
8. Update Redis seat data
9. Register presence
10. Subscribe connection to room
11. Return snapshot to joiner
12. Broadcast `room_updated` to other members

---

## 12. Acceptance Criteria

* Invalid codes are rejected with `ROOM_NOT_FOUND`
* Invalid room_code format rejected with `VALIDATION_ERROR`
* Closed rooms return `ROOM_CLOSED`
* In-game rooms return `ROOM_IN_GAME` (unless user is member)
* Full rooms return `ROOM_FULL`
* Join returns complete room snapshot
* Other room members receive `room_updated` broadcast
* Rejoining restores lobby state without duplicate seat
* Snapshot is consistent across concurrent joins

---

## 13. Definition of Done

* [x] WebSocket handler implemented
* [x] Room code resolution with authorization
* [x] Seat allocation logic
* [x] Snapshot schema validated
* [x] Redis presence correctly maintained
* [x] Broadcast to room members
* [x] Logs emitted for join attempts
