| table_name     | column_name      | data_type                |
| -------------- | ---------------- | ------------------------ |
| ws_idempotency | updated_at       | timestamp with time zone |
| profiles       | created_at       | timestamp with time zone |
| profiles       | updated_at       | timestamp with time zone |
| ws_idempotency | status           | USER-DEFINED             |
| ws_idempotency | response_payload | jsonb                    |
| ws_idempotency | created_at       | timestamp with time zone |
| profiles       | id               | uuid                     |
| rooms          | room_id          | uuid                     |
| rooms          | owner_user_id    | uuid                     |
| rooms          | visibility       | USER-DEFINED             |
| rooms          | status           | USER-DEFINED             |
| rooms          | max_players      | smallint                 |
| rooms          | ruleset_config   | jsonb                    |
| rooms          | created_at       | timestamp with time zone |
| rooms          | started_at       | timestamp with time zone |
| rooms          | closed_at        | timestamp with time zone |
| rooms          | version          | integer                  |
| room_seats     | room_id          | uuid                     |
| room_seats     | seat_index       | smallint                 |
| room_seats     | status           | USER-DEFINED             |
| room_seats     | user_id          | uuid                     |
| room_seats     | is_host          | boolean                  |
| room_seats     | ready            | USER-DEFINED             |
| room_seats     | joined_at        | timestamp with time zone |
| room_seats     | left_at          | timestamp with time zone |
| ws_idempotency | user_id          | uuid                     |
| ws_idempotency | request_id       | uuid                     |
| profiles       | display_name     | text                     |
| profiles       | avatar_url       | text                     |
| rooms          | code             | text                     |
| rooms          | ruleset_id       | text                     |