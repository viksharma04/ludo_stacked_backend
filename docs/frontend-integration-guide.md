# Ludo Stacked -- Frontend Integration Guide

This document covers everything a frontend developer needs to connect to the backend, render the board, and animate game events. All field names, message formats, and event payloads are taken directly from the backend source code.

---

## Table of Contents

1. [WebSocket Connection & Authentication](#1-websocket-connection--authentication)
2. [Room Lifecycle](#2-room-lifecycle)
3. [Game State Structure](#3-game-state-structure)
4. [Board Geometry & Rendering](#4-board-geometry--rendering)
5. [Player Actions (Client to Server)](#5-player-actions-client-to-server)
6. [Game Events (Server to Client)](#6-game-events-server-to-client)
7. [Turn Flow & Game Phases](#7-turn-flow--game-phases)
8. [Special Mechanics](#8-special-mechanics)
9. [Animation Sequencing Guide](#9-animation-sequencing-guide)
10. [Complete Message Reference](#10-complete-message-reference)

---

## 1. WebSocket Connection & Authentication

### Endpoint

```
ws://<host>/api/v1/ws
```

No query parameters or headers are needed on the initial connection. Authentication happens via a message after the socket opens.

### Connection Flow

```
1. Client opens WebSocket to ws://<host>/api/v1/ws
2. Server accepts immediately (connection is unauthenticated)
3. Server starts a 30-second authentication timeout
4. Client sends "authenticate" message with JWT + room_code
5. Server validates JWT against Supabase JWKS
6. Server validates room access (room exists, user has a seat)
7. On success: server sends "authenticated" with room snapshot
8. On failure: server sends "error" (connection stays open but unauthenticated)
9. If no authenticate message within 30 seconds: server closes with code 4005
```

### Authenticate Message

```json
{
  "type": "authenticate",
  "payload": {
    "token": "eyJhbGciOiJSUzI1NiIs...",
    "room_code": "ABC123"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | Supabase JWT access token (min 1 character) |
| `room_code` | string | Yes | Exactly 6 uppercase alphanumeric characters (`^[A-Z0-9]{6}$`) |

### Authenticated Response

On success, the server sends:

```json
{
  "type": "authenticated",
  "payload": {
    "connection_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "server_id": "server-1",
    "room": {
      "room_id": "r1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "code": "ABC123",
      "status": "open",
      "visibility": "private",
      "ruleset_id": "classic",
      "max_players": 4,
      "seats": [
        {
          "seat_index": 0,
          "user_id": "a1b2c3d4-...",
          "display_name": "Alice",
          "ready": "not_ready",
          "connected": true,
          "is_host": true
        },
        {
          "seat_index": 1,
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
}
```

### Error Response (Authentication)

```json
{
  "type": "error",
  "payload": {
    "error_code": "AUTH_FAILED",
    "message": "Invalid token: ..."
  }
}
```

Possible `error_code` values during authentication:

| Code | Description |
|------|-------------|
| `AUTH_FAILED` | JWT validation failed |
| `AUTH_EXPIRED` | JWT has expired |
| `ROOM_NOT_FOUND` | Room code does not exist or room is closed |
| `ROOM_ACCESS_DENIED` | User does not have a seat in the room |
| `ALREADY_AUTHENTICATED` | Connection is already authenticated |

### Ping/Pong Keepalive

Send a `ping` periodically (recommended every 25 seconds) to keep the connection alive. The server disconnects connections that have not sent a heartbeat within 120 seconds.

```json
// Client sends:
{
  "type": "ping",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}

// Server responds:
{
  "type": "pong",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "server_time": "2026-03-01T12:30:00Z"
  }
}
```

Pings are allowed before authentication.

### Reconnection Strategy

When the WebSocket disconnects:

1. Obtain a fresh JWT if the current one may be expired.
2. Open a new WebSocket connection.
3. Send the `authenticate` message with the fresh token and the same `room_code`.
4. On receiving `authenticated`, use the `room` payload to restore lobby state.
5. If a game is in progress, the server will send a `game_state` message with the full current state for reconciliation.

### Rate Limiting

- Maximum message size: 64 KB
- Maximum messages per second: 10

If exceeded, the server sends an error but does not close the connection:

```json
{
  "type": "error",
  "payload": {
    "error_code": "RATE_LIMITED",
    "message": "Too many messages, please slow down"
  }
}
```

### WebSocket Close Codes

| Code | Name | Description |
|------|------|-------------|
| 1001 | GOING_AWAY | Server shutdown or stale connection cleanup |
| 4005 | AUTH_TIMEOUT | Client did not authenticate within 30 seconds |

**Note:** Authentication failures (invalid JWT, expired token, room not found, room access denied) are sent as error *messages* (type `"error"`) over the connection, not as WebSocket close codes. See the error codes table above.

---

## 2. Room Lifecycle

### Creating a Room (REST)

```
POST /api/v1/rooms
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "n_players": 4
}
```

Response (201 Created):

```json
{
  "room_id": "r1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "code": "ABC123",
  "seat": {
    "seat_index": 0,
    "is_host": true
  },
  "cached": false
}
```

If the user already owns an open room, `cached: true` is returned with that room's details.

### Joining a Room (REST)

```
POST /api/v1/rooms/join
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "code": "ABC123"
}
```

Response (200 OK):

```json
{
  "room_id": "r1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "code": "ABC123",
  "seat": {
    "seat_index": 1,
    "is_host": false
  }
}
```

After creating or joining a room, establish a WebSocket connection and authenticate with the room code.

### Room Status Flow

```
open  -->  ready_to_start  -->  in_game  -->  closed
  ^            |
  |            v
  +--- (player unreadies)
```

| Status | Description |
|--------|-------------|
| `open` | Accepting players, not all players are ready |
| `ready_to_start` | All seated players are ready (minimum 2 players). Host can start the game. |
| `in_game` | Game is in progress |
| `closed` | Room closed (host left or game ended) |

### Toggling Ready

```json
{
  "type": "toggle_ready",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

The server responds with `room_updated` (to sender) and broadcasts `room_updated` to all other room members. When all seated players are ready, the room status changes to `ready_to_start`.

### Room Updated Broadcast

Sent to all room members whenever room state changes (player joins, toggles ready, connects, disconnects):

```json
{
  "type": "room_updated",
  "payload": {
    "room_id": "r1a2b3c4-...",
    "code": "ABC123",
    "status": "ready_to_start",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [
      {
        "seat_index": 0,
        "user_id": "a1b2c3d4-...",
        "display_name": "Alice",
        "ready": "ready",
        "connected": true,
        "is_host": true
      },
      {
        "seat_index": 1,
        "user_id": "b2c3d4e5-...",
        "display_name": "Bob",
        "ready": "ready",
        "connected": true,
        "is_host": false
      }
    ],
    "version": 5
  }
}
```

### Starting a Game

Only the host can start the game when room status is `ready_to_start`:

```json
{
  "type": "start_game",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

The server responds with `game_started` (containing full initial game state and startup events) and broadcasts the same `game_started` message to all room members.

### Leaving a Room

```json
{
  "type": "leave_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

- If the **host** leaves: room is closed and `room_closed` is broadcast to all remaining players.
- If a **non-host** leaves: their seat is cleared and `room_updated` is broadcast.

### Room Closed

```json
{
  "type": "room_closed",
  "payload": {
    "reason": "host_left",
    "room_id": "r1a2b3c4-..."
  }
}
```

When received, the client should close the WebSocket and navigate away from the room.

---

## 3. Game State Structure

The full game state is sent in the `game_started` message and can be requested for reconnection via `game_state`. Here is the complete structure:

### GameState

```json
{
  "phase": "in_progress",
  "players": [ ... ],
  "current_event": "player_roll",
  "board_setup": { ... },
  "current_turn": { ... },
  "event_seq": 3
}
```

| Field | Type | Description |
|-------|------|-------------|
| `phase` | string | `"not_started"`, `"in_progress"`, or `"finished"` |
| `players` | array | List of Player objects |
| `current_event` | string | What the game is waiting for: `"player_roll"`, `"player_choice"`, or `"capture_choice"` |
| `board_setup` | object | Board geometry configuration |
| `current_turn` | object or null | Current turn state (null before game starts) |
| `event_seq` | integer | Next sequence number for events (monotonically increasing) |

### Player

```json
{
  "player_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "name": "Alice",
  "color": "red",
  "turn_order": 1,
  "abs_starting_index": 0,
  "stacks": [ ... ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Unique player identifier (matches Supabase user ID) |
| `name` | string | Display name |
| `color` | string | Assigned color: `"red"`, `"blue"`, `"green"`, or `"yellow"` |
| `turn_order` | integer | 1-indexed turn position (1 goes first) |
| `abs_starting_index` | integer | Absolute board position where this player enters the road |
| `stacks` | array | List of Stack objects belonging to this player |

**Color Assignment:** Colors are assigned based on seat index:
- Seat 0: `"red"`
- Seat 1: `"blue"`
- Seat 2: `"green"`
- Seat 3: `"yellow"`

### Stack

```json
{
  "stack_id": "stack_1_3",
  "state": "road",
  "height": 2,
  "progress": 15
}
```

| Field | Type | Description |
|-------|------|-------------|
| `stack_id` | string | Composition-based identifier (see Stack ID Conventions below) |
| `state` | string | `"hell"`, `"road"`, `"homestretch"`, or `"heaven"` |
| `height` | integer | Number of pieces in this stack (1-4) |
| `progress` | integer | Position along the player's track (0 = starting position on road) |

#### Stack States

| State | Description | Rendering |
|-------|-------------|-----------|
| `hell` | Starting area. Stack is waiting to be released. | Render in the player's home/base area. |
| `road` | On the shared circular track. | Render on the board at the absolute position. |
| `homestretch` | On the player's private final lane. | Render in the player's homestretch lane. |
| `heaven` | Finished. Stack has completed its journey. | Render in the player's heaven/finish area. |

#### Stack ID Conventions

Stack IDs encode their composition:

- `"stack_1"` -- individual piece #1 (height 1)
- `"stack_2"` -- individual piece #2 (height 1)
- `"stack_1_2"` -- pieces 1 and 2 merged (height 2)
- `"stack_1_2_3"` -- pieces 1, 2, and 3 merged (height 3)
- `"stack_1_2_3_4"` -- all four pieces merged (height 4)

**Rules:**
- Component numbers are always sorted ascending within the ID.
- Each player starts with four individual stacks: `stack_1`, `stack_2`, `stack_3`, `stack_4`.
- Merging: `stack_1` + `stack_3` = `stack_1_3`
- Splitting: the **largest** component numbers peel off the top. For example, splitting 1 piece off `stack_1_2_3` produces moving=`stack_3` (top), remaining=`stack_1_2` (bottom).

### BoardSetup

```json
{
  "squares_to_win": 55,
  "squares_to_homestretch": 50,
  "starting_positions": [0, 13, 26, 39],
  "safe_spaces": [0, 7, 13, 20, 26, 33, 39, 46],
  "get_out_rolls": [6]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `squares_to_win` | integer | Progress value at which a stack reaches heaven |
| `squares_to_homestretch` | integer | Progress value at which a stack enters the homestretch |
| `starting_positions` | array of int | Absolute board positions where each player enters the road |
| `safe_spaces` | array of int | Absolute board positions where captures are not allowed |
| `get_out_rolls` | array of int | Dice values that release a stack from hell (default: `[6]`) |

### Turn

```json
{
  "player_id": "a1b2c3d4-...",
  "initial_roll": false,
  "rolls_to_allocate": [6, 3],
  "legal_moves": ["stack_1", "stack_2", "stack_3"],
  "current_turn_order": 1,
  "extra_rolls": 0,
  "pending_capture": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | The player whose turn it is |
| `initial_roll` | boolean | True if the player has not rolled yet this turn |
| `rolls_to_allocate` | array of int | Accumulated dice values not yet used for moves |
| `legal_moves` | array of string | Stack IDs (or sub-stack IDs) that can legally be moved |
| `current_turn_order` | integer | Turn order of the current player (1-indexed) |
| `extra_rolls` | integer | Extra rolls remaining (from captures) |
| `pending_capture` | object or null | Non-null when awaiting a capture choice |

### PendingCapture

```json
{
  "moving_stack_id": "stack_1_2",
  "position": 13,
  "capturable_targets": [
    "b2c3d4e5-...:stack_1",
    "c3d4e5f6-...:stack_2"
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `moving_stack_id` | string | The stack that caused the collision |
| `position` | integer | Absolute board position of the collision |
| `capturable_targets` | array of string | Target IDs in `"{player_id}:{stack_id}"` format |

---

## 4. Board Geometry & Rendering

### Grid Length and Derived Values

The standard game uses `grid_length = 6`. All geometry derives from this:

| Name | Formula | Standard Value (g=6) |
|------|---------|---------------------|
| Step (distance between starting positions) | `2g + 1` | 13 |
| Total road squares | `4 * (2g + 1)` = `8g + 4` | 52 |
| Squares to homestretch | `8g + 2` | 50 |
| Homestretch length | `g - 1` | 5 |
| Squares to win (heaven) | `9g + 1` | 55 |
| Starting positions | `[0, step, 2*step, 3*step]` | `[0, 13, 26, 39]` |
| Safe offset | `2g - 5` from each start | 7 |

### The Road (Shared Track)

The road is a circular track with `squares_to_homestretch` (50) positions, numbered 0 through 49 in absolute terms.

**Absolute position formula:**

```
abs_pos = (player.abs_starting_index + stack.progress) % squares_to_homestretch
```

This is used for:
- Rendering a stack on the board
- Collision detection (two stacks from different players at the same `abs_pos`)

### Player Starting Positions

| Player Count | Starting Positions (abs) | Color Mapping |
|-------------|--------------------------|---------------|
| 2 players | `[0, 26]` (opposite corners) | Seat 0, Seat 2 |
| 3 players | `[0, 13, 26]` | Seat 0, Seat 1, Seat 2 |
| 4 players | `[0, 13, 26, 39]` | Seat 0, Seat 1, Seat 2, Seat 3 |

Each player's road journey starts at `progress = 0`, which corresponds to their `abs_starting_index` on the board.

### Safe Spaces

Eight safe spaces exist on the board regardless of player count:

```
Absolute positions: [0, 7, 13, 20, 26, 33, 39, 46]
```

These are computed as: for each starting position `[0, 13, 26, 39]`, add the position itself and `position + (2*grid_length - 5)`.

Stacks on safe spaces **cannot be captured**.

### Homestretch

The homestretch is a per-player private lane. It is **not** part of the shared road. Each player has their own homestretch that only their stacks can enter.

A stack enters the homestretch when its `progress >= squares_to_homestretch` (50). The homestretch spans progress values 50 through 54 (5 squares for grid_length=6).

**Rendering the homestretch:** Since the homestretch is private, position it as a lane branching off from just before the player's starting position (the last square before they would "lap" the board).

### Heaven

A stack reaches heaven when `progress == squares_to_win` (55). This is the destination beyond the homestretch. Render it as the finish area at the end of the player's homestretch lane.

### Mapping Progress to Board Position

For rendering, convert a stack's `progress` value to a visual board position:

```
if stack.state == "hell":
    render in player's home/base area

elif stack.state == "road":
    abs_pos = (player.abs_starting_index + stack.progress) % board_setup.squares_to_homestretch
    render at board position abs_pos on the circular track

elif stack.state == "homestretch":
    homestretch_index = stack.progress - board_setup.squares_to_homestretch
    render at position homestretch_index in this player's homestretch lane (0..4)

elif stack.state == "heaven":
    render in player's heaven/finish area
```

### Visual Board Layout (grid_length=6)

The circular road has 52 squares total (indices 0-49 used for positioning, with the track physically having `4 * step` = 52 cells). A standard Ludo board is cross-shaped. Map the 50 homestretch-relevant positions around the cross in order.

```
Board positions (absolute indices 0-49 arranged clockwise):

         Player 3's homestretch
              [26-30]
                |
     39 38 37 36 35 34 33 32 31 30 29 28 27
  40                                        26
  41           (Player 3 home)              25  <- Player 2's
  42                                        24     homestretch
  43                                        23     entry
  44                                        22
  45           (Player 4 home)    (P2 home) 21
  46                                        20
  47                                        19
  48                                        18
  49                                        17
   0   1  2  3  4  5  6  7  8  9 10 11 12  13
                |
         Player 1's homestretch
              [0-4 from entry]
```

Note: The exact visual layout depends on your board design. The key mapping is `abs_pos` to visual cell.

---

## 5. Player Actions (Client to Server)

All game actions are sent as `game_action` messages:

```json
{
  "type": "game_action",
  "request_id": "<uuid>",
  "payload": {
    "action_type": "...",
    ...action-specific fields
  }
}
```

The `request_id` is echoed back in responses for correlation.

### 5.1 Roll Dice

Send when `current_event` is `"player_roll"` and it is your turn.

```json
{
  "type": "game_action",
  "request_id": "d3f1a2b3-c4d5-6789-abcd-ef1234567890",
  "payload": {
    "action_type": "roll",
    "value": 5
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action_type` | string | Yes | Must be `"roll"` |
| `value` | integer | Yes | Dice value, 1-6 |

**Note:** In the current architecture, the client sends the roll value. A server-side random dice roll may be implemented in the future. For now, use `Math.ceil(Math.random() * 6)` on the client.

### 5.2 Move Stack

Send when `current_event` is `"player_choice"` and you have legal moves.

```json
{
  "type": "game_action",
  "request_id": "d3f1a2b3-c4d5-6789-abcd-ef1234567890",
  "payload": {
    "action_type": "move",
    "stack_id": "stack_1",
    "roll_value": 5
  }
}
```

| Payload Field | Type | Required | Description |
|---------------|------|----------|-------------|
| `action_type` | string | Yes | `"move"` |
| `stack_id` | string | Yes | Stack ID or sub-stack ID to move (must be in `legal_moves` for the specified roll) |
| `roll_value` | integer | Yes | Which dice value from `rolls_to_allocate` to consume |

**Which stack IDs are valid?** Use the `available_moves` from the most recent `awaiting_choice` event. This provides legal moves grouped by roll value.

### 5.3 Capture Choice

Send when `current_event` is `"capture_choice"`.

```json
{
  "type": "game_action",
  "request_id": "d3f1a2b3-c4d5-6789-abcd-ef1234567890",
  "payload": {
    "action_type": "capture_choice",
    "choice": "b2c3d4e5-0000-0000-0000-000000000002:stack_1"
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `action_type` | string | Yes | `"capture_choice"` |
| `choice` | string | Yes | One of the `options` from the `awaiting_capture_choice` event |

The `choice` value must exactly match one of the strings in the `options` array. The format is `"{player_id}:{stack_id}"`.

### 5.4 Start Game

Sent by the host from the lobby (not during gameplay). Uses the `start_game` message type, not `game_action`:

```json
{
  "type": "start_game",
  "request_id": "d3f1a2b3-c4d5-6789-abcd-ef1234567890"
}
```

No payload fields needed. The server validates that the sender is the host and the room status is `"ready_to_start"`.

---

## 6. Game Events (Server to Client)

Game events arrive as `game_events` messages containing an ordered array:

```json
{
  "type": "game_events",
  "request_id": "d3f1a2b3-...",
  "payload": {
    "events": [
      { "event_type": "dice_rolled", "seq": 4, ... },
      { "event_type": "awaiting_choice", "seq": 5, ... }
    ]
  }
}
```

The `request_id` is present only in the response sent to the player who sent the action. The broadcast to other players does not include `request_id`.

Every event has:
- `event_type` (string) -- identifies the event kind
- `seq` (integer) -- monotonically increasing sequence number for ordering

**Process events in array order.** The `seq` field is for gap detection and ordering verification.

### 6.1 Game Started

**Emitted when:** The host starts the game.

**Delivery:** Sent inside the `game_started` message (not `game_events`).

```json
{
  "type": "game_started",
  "payload": {
    "game_state": { ...full GameState... },
    "events": [
      {
        "event_type": "game_started",
        "seq": 0,
        "player_order": [
          "a1b2c3d4-...",
          "b2c3d4e5-..."
        ],
        "first_player_id": "a1b2c3d4-..."
      },
      {
        "event_type": "turn_started",
        "seq": 1,
        "player_id": "a1b2c3d4-...",
        "turn_number": 1
      },
      {
        "event_type": "roll_granted",
        "seq": 2,
        "player_id": "a1b2c3d4-...",
        "reason": "turn_start"
      }
    ]
  }
}
```

**Frontend action:**
1. Store the full `game_state` for rendering.
2. Transition from lobby UI to game board UI.
3. Render all player stacks in their initial positions (all in HELL).
4. Highlight the first player as active.
5. Enable the dice roll button for the first player.

### 6.2 DiceRolled

**Emitted when:** A player rolls the dice.

```json
{
  "event_type": "dice_rolled",
  "seq": 4,
  "player_id": "a1b2c3d4-...",
  "value": 5,
  "roll_number": 1,
  "grants_extra_roll": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Who rolled |
| `value` | integer | The dice value (1-6) |
| `roll_number` | integer | Which roll this is in the current turn (1, 2, 3...) |
| `grants_extra_roll` | boolean | True if the value is 6 (player gets another roll) |

**Frontend action:**
- Animate the dice roll, landing on the rolled value.
- If `grants_extra_roll` is true, show a "Roll again!" indicator.
- Duration suggestion: 800-1200ms for the dice animation.

### 6.3 ThreeSixesPenalty

**Emitted when:** A player rolls three consecutive sixes.

```json
{
  "event_type": "three_sixes_penalty",
  "seq": 7,
  "player_id": "a1b2c3d4-...",
  "rolls": [6, 6, 6]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Who was penalized |
| `rolls` | array of int | The three sixes |

**Frontend action:**
- Show a penalty animation or notification ("Three sixes! Turn forfeited!").
- All accumulated rolls are discarded.
- The turn will end (a `TurnEnded` event follows).
- Duration suggestion: 1500ms for penalty display.

### 6.4 StackMoved

**Emitted when:** A stack moves along the road or homestretch.

```json
{
  "event_type": "stack_moved",
  "seq": 6,
  "player_id": "a1b2c3d4-...",
  "stack_id": "stack_1",
  "from_state": "road",
  "to_state": "road",
  "from_progress": 10,
  "to_progress": 15,
  "roll_used": 5
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Owner of the stack |
| `stack_id` | string | Which stack moved |
| `from_state` | string | Previous state (`"road"` or `"homestretch"`) |
| `to_state` | string | New state (`"road"`, `"homestretch"`, or `"heaven"`) |
| `from_progress` | integer | Starting progress value |
| `to_progress` | integer | Ending progress value |
| `roll_used` | integer | The dice value consumed |

**Frontend action:**
- Animate the stack moving from `from_progress` to `to_progress`.
- If `from_state != to_state`, show a transition animation (e.g., entering homestretch).
- For stacks with `height > 1`, the effective movement is `roll_used / height` squares. Animate step-by-step along the path.
- Duration suggestion: 300-500ms per square of movement.

### 6.5 StackExitedHell

**Emitted when:** A stack is released from HELL to the ROAD (player rolled a valid get-out roll, typically 6).

```json
{
  "event_type": "stack_exited_hell",
  "seq": 5,
  "player_id": "a1b2c3d4-...",
  "stack_id": "stack_2",
  "roll_used": 6
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Owner of the stack |
| `stack_id` | string | Which stack exited hell |
| `roll_used` | integer | The dice value used (always from `get_out_rolls`, typically 6) |

**Frontend action:**
- Animate the stack moving from the player's base/home area to their starting position on the road (`progress = 0`, absolute position = `player.abs_starting_index`).
- Duration suggestion: 600-800ms.

### 6.6 StackReachedHeaven

**Emitted when:** A stack reaches the heaven (winning) position.

```json
{
  "event_type": "stack_reached_heaven",
  "seq": 8,
  "player_id": "a1b2c3d4-...",
  "stack_id": "stack_1_2"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Owner of the stack |
| `stack_id` | string | Which stack reached heaven |

**Frontend action:**
- Animate the stack entering the heaven/finish area with a celebratory effect.
- This event always follows a `StackMoved` event where `to_state == "heaven"`. Process the movement animation first, then the heaven celebration.
- Duration suggestion: 800-1000ms for the celebration effect.

### 6.7 StackCaptured

**Emitted when:** A stack captures an opponent's stack.

```json
{
  "event_type": "stack_captured",
  "seq": 9,
  "capturing_player_id": "a1b2c3d4-...",
  "capturing_stack_id": "stack_1_2",
  "captured_player_id": "b2c3d4e5-...",
  "captured_stack_id": "stack_3",
  "position": 13,
  "grants_extra_roll": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `capturing_player_id` | UUID string | Player who made the capture |
| `capturing_stack_id` | string | The capturing stack |
| `captured_player_id` | UUID string | Player whose stack was captured |
| `captured_stack_id` | string | The stack that was sent to hell |
| `position` | integer | Absolute board position where capture occurred |
| `grants_extra_roll` | boolean | Always true (captures grant bonus rolls) |

**Frontend action:**
- Animate the captured stack being sent to hell (back to the captured player's base area).
- If the captured stack had `height > 1`, it gets decomposed into individual `height=1` stacks in hell (a `StackUpdate` event for the captured player will describe this).
- Show a capture effect/flash at the `position`.
- The capturing player gets extra rolls equal to the captured stack's height.
- Duration suggestion: 500-700ms for the capture animation.

### 6.8 StackUpdate

**Emitted when:** Stacks are created or dissolved due to stacking (merging) or splitting.

```json
{
  "event_type": "stack_update",
  "seq": 7,
  "player_id": "a1b2c3d4-...",
  "add_stacks": [
    {
      "stack_id": "stack_1_3",
      "state": "road",
      "height": 2,
      "progress": 15
    }
  ],
  "remove_stacks": [
    {
      "stack_id": "stack_1",
      "state": "road",
      "height": 1,
      "progress": 15
    },
    {
      "stack_id": "stack_3",
      "state": "road",
      "height": 1,
      "progress": 15
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Owner of the stacks |
| `add_stacks` | array of Stack | New stacks being created |
| `remove_stacks` | array of Stack | Old stacks being dissolved |

**Scenarios where StackUpdate is emitted:**

1. **Stacking (merging):** Two same-player stacks meet on the same square. `remove_stacks` contains both old stacks, `add_stacks` contains one merged stack.
2. **Splitting (partial move):** A sub-stack peels off a parent stack. `remove_stacks` contains the parent, `add_stacks` contains the remaining stack and the moving sub-stack.
3. **Capture decomposition:** A multi-height stack is captured and decomposed into individual stacks in HELL. The `remove_stacks` has the multi-stack; `add_stacks` has individual `height=1` stacks in HELL state.

**Frontend action:**
- For **merging**: animate the two stacks combining into one at the same position. Visually stack them.
- For **splitting**: animate the parent stack splitting. The remaining piece stays; the moving piece will be animated separately by a subsequent `StackMoved` event.
- For **capture decomposition**: animate the stack breaking apart and pieces scattering to the player's base area.
- Duration suggestion: 400-600ms.

### 6.9 TurnStarted

**Emitted when:** A new player's turn begins.

```json
{
  "event_type": "turn_started",
  "seq": 10,
  "player_id": "b2c3d4e5-...",
  "turn_number": 2
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Whose turn is starting |
| `turn_number` | integer | The turn order number |

**Frontend action:**
- Highlight the active player.
- Show a "Your turn" indicator if it is the local player.
- Instant state update (no animation needed).

### 6.10 RollGranted

**Emitted when:** A player should roll the dice. This is the server's signal that a roll is expected.

```json
{
  "event_type": "roll_granted",
  "seq": 11,
  "player_id": "b2c3d4e5-...",
  "reason": "turn_start"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Who should roll |
| `reason` | string | `"turn_start"`, `"rolled_six"`, or `"capture_bonus"` |

**Reason descriptions:**

| Reason | Description |
|--------|-------------|
| `turn_start` | Start of a new turn |
| `rolled_six` | Player rolled a 6 and gets an extra roll |
| `capture_bonus` | Player captured an opponent and gets a bonus roll |

**Frontend action:**
- Enable the dice/roll button for the specified player.
- If `reason` is `"rolled_six"`, show "Roll again!" indicator.
- If `reason` is `"capture_bonus"`, show "Bonus roll!" indicator.
- Instant state update.

### 6.11 TurnEnded

**Emitted when:** A player's turn is over.

```json
{
  "event_type": "turn_ended",
  "seq": 12,
  "player_id": "a1b2c3d4-...",
  "reason": "all_rolls_used",
  "next_player_id": "b2c3d4e5-..."
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Whose turn ended |
| `reason` | string | Why the turn ended |
| `next_player_id` | UUID string | Who goes next |

**Reason values:**

| Reason | Description |
|--------|-------------|
| `no_legal_moves` | Player has no valid moves for their rolled value(s) |
| `all_rolls_used` | Player has used all their rolls |
| `three_sixes` | Player was penalized for rolling three consecutive sixes |

**Frontend action:**
- Deactivate the current player's UI controls.
- Briefly show why the turn ended if relevant (e.g., "No legal moves!").
- Prepare for the next player's turn (a `TurnStarted` event follows).
- Instant state update.

### 6.12 AwaitingChoice

**Emitted when:** The game is waiting for the current player to choose which stack to move.

```json
{
  "event_type": "awaiting_choice",
  "seq": 5,
  "player_id": "a1b2c3d4-...",
  "available_moves": [
    {
      "roll": 6,
      "move_groups": [
        {
          "stack_id": "stack_1",
          "moves": ["stack_1"]
        },
        {
          "stack_id": "stack_2",
          "moves": ["stack_2"]
        }
      ]
    },
    {
      "roll": 3,
      "move_groups": [
        {
          "stack_id": "stack_1",
          "moves": ["stack_1"]
        }
      ]
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Who needs to choose |
| `available_moves` | array of RollMoveGroup | Legal moves grouped by roll value |

**RollMoveGroup structure:**

```json
{
  "roll": 6,
  "move_groups": [
    {
      "stack_id": "stack_1_2_3",
      "moves": ["stack_1_2_3", "stack_2_3", "stack_3"]
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `roll` | integer | The dice value this group applies to |
| `move_groups` | array of LegalMoveGroup | Legal moves grouped by parent stack |

**LegalMoveGroup structure:**

| Field | Type | Description |
|-------|------|-------------|
| `stack_id` | string | The parent stack ID |
| `moves` | array of string | Legal move IDs (parent stack or sub-stacks) |

Within a `LegalMoveGroup`:
- The first entry is typically the full stack move.
- Additional entries are partial (split) moves where a sub-stack peels off.
- Example: `"moves": ["stack_1_2_3", "stack_2_3", "stack_3"]` means you can move the full height-3 stack, or split off a height-2 sub-stack, or split off a height-1 sub-stack.

**Frontend action:**
- If only one roll value has legal moves and only one move option: you may auto-select or highlight it, but the player must still confirm.
- Highlight all movable stacks on the board.
- When the player taps a stack, show which roll values can be used with it.
- When the player confirms a move, send a `game_action` with `action_type: "move"`, the chosen `stack_id`, and the `roll_value`.

### 6.13 AwaitingCaptureChoice

**Emitted when:** A stack lands on a square with multiple capturable opponents.

```json
{
  "event_type": "awaiting_capture_choice",
  "seq": 10,
  "player_id": "a1b2c3d4-...",
  "options": [
    "b2c3d4e5-0000-0000-0000-000000000002:stack_1",
    "c3d4e5f6-0000-0000-0000-000000000003:stack_2"
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `player_id` | UUID string | Who must choose |
| `options` | array of string | Capturable targets in `"{player_id}:{stack_id}"` format |

**Frontend action:**
- Highlight the capturable opponent stacks on the board.
- Present a selection UI for the player to choose which opponent to capture.
- The chosen value must be sent exactly as it appears in the `options` array.
- Duration: wait for player input (no timer enforced by server).

### 6.14 GameEnded

**Emitted when:** A player has all their stacks in heaven.

```json
{
  "event_type": "game_ended",
  "seq": 99,
  "winner_id": "a1b2c3d4-...",
  "final_rankings": [
    "a1b2c3d4-...",
    "b2c3d4e5-..."
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `winner_id` | UUID string | The winning player |
| `final_rankings` | array of UUID string | Players in finishing order |

**Frontend action:**
- Show victory screen with the winner highlighted.
- Display final rankings.
- Optionally animate all of the winner's stacks in a celebration.
- Disable all game controls.

---

## 7. Turn Flow & Game Phases

### Game Phases

```
NOT_STARTED  -->  IN_PROGRESS  -->  FINISHED
```

- `NOT_STARTED`: Game state exists but `start_game` has not been sent.
- `IN_PROGRESS`: Active gameplay. `current_turn` is non-null.
- `FINISHED`: A player has won. No more actions accepted.

### CurrentEvent (What the Game is Waiting For)

| Value | Description | Expected Action |
|-------|-------------|-----------------|
| `player_roll` | Waiting for dice roll | Send `RollAction` |
| `player_choice` | Waiting for move selection | Send `MoveAction` |
| `capture_choice` | Waiting for capture target selection | Send `CaptureChoiceAction` |

### Standard Turn Flow

```
TurnStarted + RollGranted(reason="turn_start")
    |
    v
Player rolls dice (RollAction)
    |
    v
DiceRolled
    |
    +--[value == 6]--> RollGranted(reason="rolled_six") --> Player rolls again
    |                                                           |
    |                                                           v
    |                                                     DiceRolled
    |                                                       (repeat up to penalty)
    |
    +--[value != 6 AND has legal moves]--> AwaitingChoice
    |                                           |
    |                                           v
    |                                     Player selects move (MoveAction)
    |                                           |
    |                                           v
    |                                     StackMoved (+ possible StackUpdate, StackCaptured, etc.)
    |                                           |
    |                                           +--[more rolls_to_allocate with legal moves]--> AwaitingChoice
    |                                           +--[extra_rolls > 0]--> RollGranted(reason="capture_bonus")
    |                                           +--[no more rolls/moves]--> TurnEnded
    |
    +--[value != 6 AND no legal moves]--> TurnEnded(reason="no_legal_moves")
```

### Multi-Roll Allocation

When a player rolls a 6, they get an extra roll. This accumulates rolls in `rolls_to_allocate`:

1. Player rolls 6 --> `rolls_to_allocate: [6]`, gets extra roll.
2. Player rolls 3 --> `rolls_to_allocate: [6, 3]`, no extra roll (not a 6).
3. Game presents `AwaitingChoice` with moves grouped by roll value.
4. Player picks a move with `roll_value: 6` --> executes move, `rolls_to_allocate: [3]`.
5. Game presents `AwaitingChoice` again with moves for remaining roll value 3.
6. Player picks a move with `roll_value: 3` --> executes move, turn ends.

**Key points:**
- Identical roll values are deduplicated in the `available_moves` grouping (e.g., two 6s show as one entry with `roll: 6`), but each move consumes one instance from `rolls_to_allocate`.
- If no roll value has any legal moves, all remaining rolls are discarded and the turn ends.
- The player must specify `roll_value` in the `MoveAction` to indicate which roll to consume.

### Three Sixes Penalty

If a player accumulates three consecutive sixes (i.e., `rolls_to_allocate` ends with `[..., 6, 6, 6]`), all rolls are forfeited and the turn immediately ends.

Event sequence:
```
DiceRolled(value=6, roll_number=3, grants_extra_roll=false)  -- the penalized roll does NOT grant an extra roll
ThreeSixesPenalty(rolls=[6,6,6])
TurnEnded(reason="three_sixes", next_player_id=...)
TurnStarted(player_id=next_player)
RollGranted(player_id=next_player, reason="turn_start")
```

### Extra Rolls from Captures

When a player captures an opponent's stack, they receive extra rolls equal to the captured stack's height:
- Capture a `height=1` stack: 1 bonus roll
- Capture a `height=2` stack: 2 bonus rolls
- Capture a `height=3` stack: 3 bonus rolls

These bonus rolls are consumed one at a time via `RollGranted(reason="capture_bonus")` after all current `rolls_to_allocate` are used.

---

## 8. Special Mechanics

### 8.1 Stacking (Same-Player Merges)

When two stacks belonging to the **same player** land on the **same square** (same absolute position on the road, or same progress on the homestretch), they automatically merge into a single stack.

**How it works:**
- The new stack's `height` is the sum of both stacks' heights.
- The new `stack_id` is formed by sorting and joining all component numbers (e.g., `stack_1` + `stack_3` = `stack_1_3`).
- The merged stack stays at the position where the collision occurred.

**Events emitted:**
1. `StackMoved` -- the moving stack arrives at the position
2. `StackUpdate` -- `remove_stacks` has both old stacks, `add_stacks` has the merged stack

**Rendering:** Visually stack the pieces on top of each other. Show the height (e.g., number badge or stacked tokens).

### 8.2 Movement Rules for Stacks

The effective movement for a stack of height `h` with dice roll `r` is:

```
effective_roll = r / h
```

This means:
- A `height=1` stack moves the full roll value.
- A `height=2` stack requires an even roll: 2 moves 1 square, 4 moves 2 squares, 6 moves 3 squares.
- A `height=3` stack requires a roll divisible by 3: 3 moves 1 square, 6 moves 2 squares.
- A `height=4` stack requires a roll divisible by 4: 4 moves 1 square.

If the roll is not divisible by the stack height, the full stack cannot move. However, the player may be able to **split** the stack (see 8.3).

### 8.3 Splitting (Partial Stack Moves)

A stack with `height > 1` can be split. The player chooses a sub-stack to move, leaving the rest behind.

**Splitting rules:**
- The moving sub-stack is formed from the **largest** component numbers (top of the stack).
- The roll must be divisible by the moving sub-stack's height.
- Example: `stack_1_2_3` (height 3) with roll 4:
  - Full stack: 4 / 3 is not an integer -- cannot move full stack.
  - Split off 1 (top = `stack_3`): 4 / 1 = 4 squares -- legal.
  - Split off 2 (top = `stack_2_3`): 4 / 2 = 2 squares -- legal.
  - Remaining after split of 1: `stack_1_2`. After split of 2: `stack_1`.

**Events emitted:**
1. `StackUpdate` -- `remove_stacks` has the parent, `add_stacks` has remaining + moving stacks
2. `StackMoved` -- the moving sub-stack moves to its new position

**Rendering:** Animate the top piece(s) peeling off the stack and moving independently.

### 8.4 Captures (Landing on Opponents)

When a stack lands on a square occupied by an **opponent's** stack on the road:

1. **Height check:** The moving stack's height must be >= the opponent's stack height.
   - If moving height >= opponent height: capture occurs.
   - If moving height < opponent height: no capture; stacks coexist on the same square.

2. **Safe space check:** If the square is a safe space, no capture occurs regardless of height.

3. **Capture resolution:**
   - The captured stack is sent to HELL.
   - If the captured stack has `height > 1`, it decomposes into individual `height=1` stacks in HELL.
   - The capturing player receives extra rolls equal to the captured stack's height.

**Events emitted:**
1. `StackCaptured` -- describes the capture
2. Possibly `StackUpdate` for the captured player (if their stack decomposes)

### 8.5 Capture Chains

A capture chain occurs when a stack moves, captures an opponent, gets a bonus roll, and the bonus roll enables another capture. Each capture grants more bonus rolls, potentially continuing the chain.

**Example sequence:**
```
StackMoved(stack_1, progress 10 -> 16)
StackCaptured(captured stack_A at position 16, grants_extra_roll=true)
  -- after all current rolls are used --
RollGranted(reason="capture_bonus")
DiceRolled(value=4)
AwaitingChoice(...)
StackMoved(stack_1, progress 16 -> 20)
StackCaptured(captured stack_B at position 20, grants_extra_roll=true)
  -- more bonus rolls pending --
RollGranted(reason="capture_bonus")
...
```

### 8.6 Capture Choice (Multiple Targets)

When a stack lands on a square with **multiple capturable opponents** (all with height <= the moving stack), the game pauses and asks the player to choose which one to capture.

**Events emitted:**
1. `StackMoved` -- the moving stack arrives
2. `AwaitingCaptureChoice` -- presents options to the player

The player sends a `CaptureChoiceAction` with one of the target strings. After the choice is resolved, the turn continues normally (remaining rolls, bonus rolls, or turn end).

### 8.7 HELL State and Getting Out

All stacks start in HELL. To exit hell, a player must roll a value from `get_out_rolls` (default: `[6]`).

**Rules:**
- A hell stack uses the entire roll just to enter the road at `progress = 0`. It does not advance further with that roll.
- Multiple hell stacks can exit on the same turn if the player rolls multiple 6s.
- A 6 used to exit hell is consumed from `rolls_to_allocate` like any other move.

**Events emitted:**
- `StackExitedHell` -- stack moves from HELL to ROAD

### 8.8 Safe Spaces

Eight safe spaces exist on every board. Stacks on a safe space:
- Cannot be captured by opponents.
- Can still merge with same-player stacks (stacking is always allowed).

Multiple stacks from different players can coexist on a safe space.

Safe space absolute positions (for grid_length=6): `[0, 7, 13, 20, 26, 33, 39, 46]`

**Rendering:** Visually mark safe spaces on the board (e.g., with a star or shield icon).

### 8.9 Homestretch Rules

The homestretch is a per-player private lane. Only the owning player's stacks can enter it.

**Rules:**
- A stack enters the homestretch when `progress >= squares_to_homestretch` (50).
- Stacks in the homestretch cannot be captured (they are not on the shared road).
- Same-player stacks can still merge on the homestretch if they land on the same progress value.
- A stack must land **exactly** on `squares_to_win` (55) to reach heaven. If a move would overshoot, it is not a legal move.

### 8.10 Heaven and Winning

A stack reaches heaven when `progress == squares_to_win` (55).

**Win condition:** A player wins when **all** their stacks are in HEAVEN.

When the win condition is met, a `GameEnded` event is emitted with the winner and final rankings.

---

## 9. Animation Sequencing Guide

### Core Principle: Process Events Sequentially

Events arrive as an ordered array within a single `game_events` message. **Always process them in order, waiting for each animation to complete before starting the next.**

### Event Categories

**Instant state updates (no animation needed):**
- `turn_started` -- highlight active player
- `roll_granted` -- enable dice button
- `turn_ended` -- deactivate controls

**Short animations (400-800ms):**
- `dice_rolled` -- dice tumble and land
- `stack_exited_hell` -- piece slides from base to road start
- `stack_update` (merge) -- pieces combine
- `stack_update` (split) -- piece peels off stack

**Medium animations (500-1200ms):**
- `stack_moved` -- piece slides along the path
- `stack_captured` -- captured piece flies back to base

**Long animations (800-1500ms):**
- `stack_reached_heaven` -- celebration effect
- `three_sixes_penalty` -- penalty notification
- `game_ended` -- victory screen

**Player input required (no animation, wait for response):**
- `awaiting_choice` -- highlight legal moves
- `awaiting_capture_choice` -- highlight capturable targets

### Example: Full Roll-and-Move Sequence

A player rolls 5, moves a stack that captures an opponent:

```
Events received: [
  DiceRolled,           // 1. Animate dice: 800ms
  AwaitingChoice,       // 2. Show legal moves: instant, wait for player
  -- player selects move --
  StackMoved,           // 3. Animate movement: 1500ms (5 squares * 300ms)
  StackCaptured,        // 4. Capture animation: 600ms
  TurnEnded,            // 5. Deactivate controls: instant
  TurnStarted,          // 6. Highlight next player: instant
  RollGranted           // 7. Enable dice for next player: instant
]
```

Note: Steps 1-2 arrive in one `game_events` message (response to the roll action). Steps 3-7 arrive in a second `game_events` message (response to the move action).

### Handling Split Moves

When a split move occurs, the events arrive in this order:

```
Events: [
  StackUpdate,    // 1. Animate split: parent disappears, remaining + moving appear
  StackMoved,     // 2. Animate the moving sub-stack sliding to new position
  ...             // 3. Possible collision events (StackUpdate for merge, StackCaptured, etc.)
]
```

**Sequence suggestion:**
1. Animate the split (300ms): show the parent breaking into two parts.
2. Animate the moving part traveling (300ms/square).
3. If a merge follows, animate the merge (400ms).
4. If a capture follows, animate the capture (600ms).

### Handling Rapid Events

Some event sequences should be shown together rather than with full individual animations:

- `TurnEnded` + `TurnStarted` + `RollGranted`: Show as a single "turn change" transition (500ms total).
- `ThreeSixesPenalty` + `TurnEnded` + `TurnStarted` + `RollGranted`: Show penalty (1000ms), then turn change (500ms).
- `StackMoved` + `StackReachedHeaven`: Movement animation flows into the heaven celebration seamlessly.

### Sequence Number Gap Detection

Use the `seq` field to detect missed events. If you receive an event with `seq` that does not follow the last seen `seq`, you may have missed messages. Request a full `game_state` to reconcile.

---

## 10. Complete Message Reference

### Client to Server Messages

All client messages follow this structure:

```json
{
  "type": "<message_type>",
  "request_id": "<uuid>",
  "payload": { ... }
}
```

`request_id` is optional but recommended for correlating responses. It must be a valid UUID when provided.

#### `authenticate`

Authenticate the WebSocket connection. Must be the first message sent.

```json
{
  "type": "authenticate",
  "payload": {
    "token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
    "room_code": "ABC123"
  }
}
```

| Payload Field | Type | Required | Constraints |
|---------------|------|----------|-------------|
| `token` | string | Yes | Non-empty Supabase JWT |
| `room_code` | string | Yes | Exactly 6 chars, `^[A-Z0-9]{6}$` |

#### `ping`

Keepalive heartbeat. Allowed before authentication.

```json
{
  "type": "ping",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

No payload.

#### `toggle_ready`

Toggle the player's ready state in the lobby. Requires authentication.

```json
{
  "type": "toggle_ready",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

No payload.

#### `leave_room`

Leave the current room. Requires authentication.

```json
{
  "type": "leave_room",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

No payload.

#### `start_game`

Start the game. Requires authentication and host privileges. Room must be in `ready_to_start` status.

```json
{
  "type": "start_game",
  "request_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

No payload.

#### `game_action` (roll)

Roll the dice. Send when `current_event == "player_roll"`.

```json
{
  "type": "game_action",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "action_type": "roll",
    "value": 5
  }
}
```

| Payload Field | Type | Required | Constraints |
|---------------|------|----------|-------------|
| `action_type` | string | Yes | `"roll"` |
| `value` | integer | Yes | 1-6 |

#### `game_action` (move)

Move a stack. Send when `current_event == "player_choice"`.

```json
{
  "type": "game_action",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "action_type": "move",
    "stack_id": "stack_1",
    "roll_value": 5
  }
}
```

| Payload Field | Type | Required | Constraints |
|---------------|------|----------|-------------|
| `action_type` | string | Yes | `"move"` |
| `stack_id` | string | Yes | Must be in `legal_moves` for the specified roll |
| `roll_value` | integer | Yes | Must be in `rolls_to_allocate` |

#### `game_action` (capture_choice)

Choose a capture target. Send when `current_event == "capture_choice"`.

```json
{
  "type": "game_action",
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "payload": {
    "action_type": "capture_choice",
    "choice": "b2c3d4e5-0000-0000-0000-000000000002:stack_1"
  }
}
```

| Payload Field | Type | Required | Constraints |
|---------------|------|----------|-------------|
| `action_type` | string | Yes | `"capture_choice"` |
| `choice` | string | Yes | Must be one of the `options` from `awaiting_capture_choice` |

### Server to Client Messages

All server messages follow this structure:

```json
{
  "type": "<message_type>",
  "request_id": "<uuid or null>",
  "payload": { ... }
}
```

`request_id` is present when responding to a specific client request.

#### `authenticated`

Sent after successful authentication.

```json
{
  "type": "authenticated",
  "payload": {
    "connection_id": "550e8400-...",
    "user_id": "a1b2c3d4-...",
    "server_id": "server-1",
    "room": {
      "room_id": "r1a2b3c4-...",
      "code": "ABC123",
      "status": "open",
      "visibility": "private",
      "ruleset_id": "classic",
      "max_players": 4,
      "seats": [
        {
          "seat_index": 0,
          "user_id": "a1b2c3d4-...",
          "display_name": "Alice",
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

#### `pong`

Response to `ping`.

```json
{
  "type": "pong",
  "request_id": "550e8400-...",
  "payload": {
    "server_time": "2026-03-01T12:30:00.000000"
  }
}
```

#### `room_updated`

Broadcast when room state changes (player joins, readies, connects, disconnects).

```json
{
  "type": "room_updated",
  "request_id": "550e8400-...",
  "payload": {
    "room_id": "r1a2b3c4-...",
    "code": "ABC123",
    "status": "ready_to_start",
    "visibility": "private",
    "ruleset_id": "classic",
    "max_players": 4,
    "seats": [ ... ],
    "version": 5
  }
}
```

The `request_id` is present in the response to the requester, absent in the broadcast to others.

#### `room_closed`

Broadcast when the host leaves the room.

```json
{
  "type": "room_closed",
  "payload": {
    "reason": "host_left",
    "room_id": "r1a2b3c4-..."
  }
}
```

#### `game_started`

Sent to all room members when the host starts the game. Contains the full initial game state and startup events.

```json
{
  "type": "game_started",
  "request_id": "550e8400-...",
  "payload": {
    "game_state": {
      "phase": "in_progress",
      "players": [
        {
          "player_id": "a1b2c3d4-...",
          "name": "Alice",
          "color": "red",
          "turn_order": 1,
          "abs_starting_index": 0,
          "stacks": [
            { "stack_id": "stack_1", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_2", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_3", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_4", "state": "hell", "height": 1, "progress": 0 }
          ]
        },
        {
          "player_id": "b2c3d4e5-...",
          "name": "Bob",
          "color": "blue",
          "turn_order": 2,
          "abs_starting_index": 26,
          "stacks": [
            { "stack_id": "stack_1", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_2", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_3", "state": "hell", "height": 1, "progress": 0 },
            { "stack_id": "stack_4", "state": "hell", "height": 1, "progress": 0 }
          ]
        }
      ],
      "current_event": "player_roll",
      "board_setup": {
        "squares_to_win": 55,
        "squares_to_homestretch": 50,
        "starting_positions": [0, 26],
        "safe_spaces": [0, 7, 13, 20, 26, 33, 39, 46],
        "get_out_rolls": [6]
      },
      "current_turn": {
        "player_id": "a1b2c3d4-...",
        "initial_roll": true,
        "rolls_to_allocate": [],
        "legal_moves": [],
        "current_turn_order": 1,
        "extra_rolls": 0,
        "pending_capture": null
      },
      "event_seq": 3
    },
    "events": [
      {
        "event_type": "game_started",
        "seq": 0,
        "player_order": ["a1b2c3d4-...", "b2c3d4e5-..."],
        "first_player_id": "a1b2c3d4-..."
      },
      {
        "event_type": "turn_started",
        "seq": 1,
        "player_id": "a1b2c3d4-...",
        "turn_number": 1
      },
      {
        "event_type": "roll_granted",
        "seq": 2,
        "player_id": "a1b2c3d4-...",
        "reason": "turn_start"
      }
    ]
  }
}
```

The `request_id` is present in the response to the host; absent in the broadcast to others.

#### `game_events`

Broadcast to all room members after a game action is processed. Contains the events that occurred.

```json
{
  "type": "game_events",
  "request_id": "550e8400-...",
  "payload": {
    "events": [
      {
        "event_type": "dice_rolled",
        "seq": 3,
        "player_id": "a1b2c3d4-...",
        "value": 6,
        "roll_number": 1,
        "grants_extra_roll": true
      },
      {
        "event_type": "roll_granted",
        "seq": 4,
        "player_id": "a1b2c3d4-...",
        "reason": "rolled_six"
      }
    ]
  }
}
```

The `request_id` is present in the response to the acting player; absent in the broadcast to others.

#### `game_state`

Contains the full game state for reconnection synchronization.

```json
{
  "type": "game_state",
  "payload": {
    "state": { ...full GameState object... }
  }
}
```

#### `game_error`

Sent to the player who submitted an invalid game action.

```json
{
  "type": "game_error",
  "request_id": "550e8400-...",
  "payload": {
    "error_code": "NOT_YOUR_TURN",
    "message": "It's not your turn"
  }
}
```

**Game error codes:**

| Code | Description |
|------|-------------|
| `NOT_YOUR_TURN` | Action sent by the wrong player |
| `INVALID_ACTION` | Wrong action type for current game phase |
| `ILLEGAL_MOVE` | Stack is not in the list of legal moves |
| `INVALID_ROLL` | Roll value not in `rolls_to_allocate` |
| `GAME_NOT_FOUND` | No active game for this room |
| `GAME_ALREADY_STARTED` | Game is already in progress |
| `GAME_NOT_STARTED` | Game has not started yet |
| `GAME_FINISHED` | Game has already ended |
| `NOT_HOST` | Only the host can start the game |
| `PLAYERS_NOT_READY` | Not all players are ready |
| `NOT_IN_ROOM` | Player is not in a room |
| `INVALID_CAPTURE_TARGET` | Capture choice is not valid |
| `NO_PENDING_CAPTURE` | No capture to resolve |
| `STACK_NOT_FOUND` | Referenced stack does not exist |
| `INVALID_GAME_STATE` | Game state is corrupted |
| `VALIDATION_ERROR` | Payload validation failed |

#### `error`

General error, not game-specific.

```json
{
  "type": "error",
  "request_id": "550e8400-...",
  "payload": {
    "error_code": "NOT_AUTHENTICATED",
    "message": "Authentication required. Send an 'authenticate' message first."
  }
}
```

**General error codes:**

| Code | Description |
|------|-------------|
| `NOT_AUTHENTICATED` | Action requires authentication |
| `AUTH_FAILED` | JWT validation failed |
| `AUTH_EXPIRED` | JWT has expired |
| `ALREADY_AUTHENTICATED` | Connection is already authenticated |
| `ROOM_NOT_FOUND` | Room does not exist |
| `ROOM_ACCESS_DENIED` | User does not have a seat in the room |
| `INVALID_JSON` | Message is not valid JSON |
| `INVALID_MESSAGE` | Message structure is invalid |
| `MESSAGE_TOO_LARGE` | Message exceeds 64 KB limit |
| `RATE_LIMITED` | Too many messages per second |
| `VALIDATION_ERROR` | Payload validation failed |
| `CONNECTION_NOT_FOUND` | Internal error: connection lost |
