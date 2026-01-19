# Story 1.1: Create Private Room (WS-Only)

**Role:** Backend Implementation Agent

**Stack:** FastAPI, WebSockets, Postgres (SQLAlchemy/Tortoise), Redis (aioredis)

---

## 🛠 Context & Constraints

* **Database Schema:** Immutable. You must implement APIs against the existing tables.
* **Protocol:** **WS-only**. No HTTP endpoints are to be added for this story.
* **Data Strategy:** * **Postgres:** Durable source of truth for room existence.
* **Redis:** Cache for live room/lobby state.


* **Idempotency:** Must use the Postgres table `ws_idempotency` (Not Redis).
* **Authority:** Server-authoritative logic.

---

## 🗄 DB Tables Available (Read/Write)

### 1. `rooms`

| Column | Type | Constraints |
| --- | --- | --- |
| `room_id` | UUID | PK |
| `owner_user_id` | UUID | FK -> `users.user_id` |
| `code` | Text | UNIQUE, NOT NULL (6-char Base32) |
| `visibility` | Enum | 'public', 'private' (Default: 'private') |
| `status` | Enum | 'open', 'in_game', 'closed' (Default: 'open') |
| `max_players` | Smallint | Default: 4 (Range: 2–4) |
| `ruleset_id` | Text | NOT NULL |
| `ruleset_config` | JSONB | Default: `{}` |
| `version` | Integer | Default: 0 |

### 2. `room_seats`

| Column | Type | Constraints |
| --- | --- | --- |
| `room_id` | UUID | FK -> `rooms.room_id` (Cascade) |
| `seat_index` | Smallint | 0–3 |
| `status` | Enum | 'empty', 'occupied' |
| `user_id` | UUID | FK -> `users.user_id` (Nullable) |
| `is_host` | Boolean | Default: false |
| `ready` | Enum | 'not_ready', 'ready' |

### 3. `ws_idempotency`

| Column | Type | Constraints |
| --- | --- | --- |
| `user_id` | UUID | PK (Part 1), FK -> `users.user_id` |
| `request_id` | UUID | PK (Part 2) |
| `status` | Enum | 'in_progress', 'completed', 'failed' |
| `response_payload` | JSONB | Results of the operation |

---

## ⚡ Redis State Configuration

After the DB transaction succeeds, initialize the following keys using a **pipeline**:

### 1. `room:{room_id}:meta` (HASH)

* `status`, `visibility`, `owner_user_id`, `code`, `max_players`, `ruleset_id`, `ruleset_config`, `created_at_ms`, `version`.

### 2. `room:{room_id}:seats` (HASH)

* `seat:0`: JSON string containing `user_id`, `display_name`, `ready`, `connected`, `is_host`, `joined_at_ms`.
* `seat:1-3`: Empty JSON object `{}`.

---

## 📩 Message Contract

### Client → Server: `create_room`

```json
{
  "type": "create_room",
  "request_id": "<uuid>",
  "payload": {
    "visibility": "private",
    "max_players": 4,
    "ruleset_id": "classic",
    "ruleset_config": {}
  }
}

```

### Server → Client Success: `create_room_ok`

```json
{
  "type": "create_room_ok",
  "request_id": "<uuid>",
  "payload": {
    "room_id": "<uuid>",
    "code": "AB12CD",
    "seat_index": 0,
    "is_host": true
  }
}

```

---

## ⚙️ Functional Requirements

1. **Validation:** * `visibility` must be "private".
* `max_players` must be between 2 and 4.
* `ruleset_id` must be "classic".


2. **Idempotency Check:** * Start DB Transaction.
* Insert `in_progress` into `ws_idempotency`.
* If conflict: return stored payload (if `completed`) or error (if `in_progress`).


3. **Room Creation:**
* Generate a 6-character Base32 join code.
* Handle collisions with a retry loop (up to N times).
* Insert `rooms` record and 4 `room_seats` records (Seat 0 = Host).


4. **Finalization:**
* Update `ws_idempotency` to `completed` + store payload.
* Commit DB transaction.
* Initialize Redis (best-effort; log failures but do not rollback DB).
* Subscribe connection to the room's pub/sub channel.



---

## 🧪 Test Cases

1. **Idempotency:** Verify that sending the same `request_id` twice results in the same response without creating a second room.
2. **Collision Logic:** Mock the code generator to produce a duplicate; verify the system retries and generates a new unique code.
3. **Consistency:** Ensure that if Redis is down, the room is still successfully created in Postgres and the user receives a success response.