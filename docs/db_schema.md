# Database Schema

Supabase PostgreSQL database schema for Ludo Stacked.

## Overview

The database uses Supabase with Row-Level Security (RLS) policies. Authentication is handled by Supabase Auth, and all tables reference `auth.users` for user relationships.

## Tables

### profiles

User profile information extending Supabase Auth users.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | uuid | NO | Primary key, references `auth.users(id)` |
| `display_name` | text | YES | User's display name (1-50 chars) |
| `avatar_url` | text | YES | URL to user's avatar image |
| `created_at` | timestamptz | NO | Profile creation timestamp |
| `updated_at` | timestamptz | NO | Last update timestamp |

**RLS Policies:**
- Users can read their own profile
- Users can update their own profile

---

### rooms

Game room records.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `room_id` | uuid | NO | Primary key |
| `owner_user_id` | uuid | NO | Room creator, references `auth.users(id)` |
| `code` | text | NO | Unique 6-character join code (A-Z, 0-9) |
| `status` | room_status | NO | Room lifecycle state (see enum below) |
| `visibility` | room_visibility | NO | Room visibility setting |
| `max_players` | smallint | NO | Maximum players (2-4) |
| `ruleset_id` | text | YES | Game ruleset identifier (default: 'classic') |
| `ruleset_config` | jsonb | YES | Ruleset-specific configuration |
| `created_at` | timestamptz | NO | Room creation timestamp |
| `started_at` | timestamptz | YES | When game started (null if not started) |
| `closed_at` | timestamptz | YES | When room closed (null if open) |
| `version` | integer | NO | Optimistic locking version, incremented on updates |

**Indexes:**
- Unique index on `code`
- Index on `owner_user_id`
- Index on `status`

---

### room_seats

Player seats within a room. Each room has `max_players` seats.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `room_id` | uuid | NO | References `rooms(room_id)` |
| `seat_index` | smallint | NO | Seat position (0 to max_players-1) |
| `user_id` | uuid | YES | User occupying seat, null if empty |
| `is_host` | boolean | NO | Whether this seat is the room host |
| `ready` | ready_status | NO | Player ready state |
| `connected` | boolean | NO | Whether player has active WebSocket connection |
| `status` | seat_status | NO | Seat lifecycle state |
| `joined_at` | timestamptz | YES | When user joined this seat |
| `left_at` | timestamptz | YES | When user left this seat |

**Primary Key:** `(room_id, seat_index)`

**Indexes:**
- Index on `user_id`
- Index on `(room_id, user_id)` for lookups

---

### ws_idempotency

Idempotency tracking for room creation RPC calls.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `request_id` | uuid | NO | Primary key, client-provided idempotency key |
| `user_id` | uuid | NO | User who made the request |
| `status` | idempotency_status | NO | Request status |
| `response_payload` | jsonb | YES | Cached response for duplicate requests |
| `created_at` | timestamptz | NO | Request timestamp |
| `updated_at` | timestamptz | NO | Last update timestamp |

**Primary Key:** `request_id`

---

## Enums

### room_status

Room lifecycle states:

| Value | Description |
|-------|-------------|
| `open` | Accepting players, not all ready |
| `ready_to_start` | All players ready (min 2), can start game |
| `in_game` | Game in progress |
| `closed` | Room closed (host left or game ended) |

### room_visibility

| Value | Description |
|-------|-------------|
| `private` | Join by code only |
| `public` | Visible in room list (future) |

### ready_status

| Value | Description |
|-------|-------------|
| `not_ready` | Player not ready |
| `ready` | Player ready to start |

### seat_status

| Value | Description |
|-------|-------------|
| `occupied` | Seat has a player |
| `vacant` | Seat is empty |
| `left` | Player left the seat |

### idempotency_status

| Value | Description |
|-------|-------------|
| `pending` | Request in progress |
| `completed` | Request completed successfully |
| `failed` | Request failed |

---

## RPC Functions

### find_or_create_room

Atomically finds an existing open room for a user or creates a new one.

**Parameters:**
- `p_user_id` (uuid) - User ID
- `p_request_id` (uuid) - Idempotency key
- `p_n_players` (int) - Number of players (2-4)
- `p_visibility` (text) - Room visibility
- `p_ruleset_id` (text) - Ruleset identifier

**Returns:**
- `room_id` (uuid)
- `code` (text) - 6-character join code
- `seat_index` (int) - Assigned seat
- `is_host` (boolean)
- `cached` (boolean) - True if returning cached result

**Behavior:**
1. Checks idempotency table for existing request
2. If found, returns cached response
3. Checks for user's existing open room
4. If found, returns that room
5. Creates new room with unique code (retry on collision)
6. Creates seat records
7. Returns new room data

---

## Relationships

```
auth.users
    │
    ├──< profiles (1:1)
    │
    ├──< rooms (1:N via owner_user_id)
    │
    └──< room_seats (1:N via user_id)
           │
           └──> rooms (N:1 via room_id)
```

---

## Notes

### Row-Level Security

All tables have RLS enabled. Policies ensure:
- Users can only access their own profile
- Users can only access rooms they own or have seats in
- Seat operations are restricted to the seat's user

### Timestamps

All timestamps use `timestamptz` (timestamp with time zone) and default to `now()` on insert.

### Optimistic Locking

The `rooms.version` column enables optimistic locking for concurrent updates. Increment version on every update and check expected version in WHERE clause.
