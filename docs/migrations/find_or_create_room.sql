-- Migration: find_or_create_room RPC function
-- Run this in Supabase SQL Editor

CREATE OR REPLACE FUNCTION find_or_create_room(
    p_user_id uuid,
    p_max_players smallint,
    p_visibility text DEFAULT 'private',
    p_ruleset_id text DEFAULT 'classic',
    p_ruleset_config jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_existing_room record;
    v_existing_seat record;
    v_room_id uuid;
    v_code text;
    v_attempt int := 0;
    v_max_attempts int := 10;
    i int;
BEGIN
    -- Check for existing open room owned by user
    SELECT room_id, code INTO v_existing_room
    FROM rooms
    WHERE owner_user_id = p_user_id AND status = 'open'
    LIMIT 1;

    IF v_existing_room IS NOT NULL THEN
        -- Get user's seat in the existing room
        SELECT seat_index, is_host INTO v_existing_seat
        FROM room_seats
        WHERE room_id = v_existing_room.room_id AND user_id = p_user_id
        LIMIT 1;

        RETURN jsonb_build_object(
            'success', true,
            'cached', true,
            'data', jsonb_build_object(
                'room_id', v_existing_room.room_id,
                'code', v_existing_room.code,
                'seat_index', COALESCE(v_existing_seat.seat_index, 0),
                'is_host', COALESCE(v_existing_seat.is_host, true)
            )
        );
    END IF;

    -- Generate unique room code with retry
    LOOP
        v_attempt := v_attempt + 1;
        IF v_attempt > v_max_attempts THEN
            RETURN jsonb_build_object(
                'success', false,
                'error', 'CODE_GENERATION_FAILED',
                'message', 'Failed to generate unique room code'
            );
        END IF;

        v_code := upper(substring(md5(random()::text || clock_timestamp()::text) from 1 for 6));

        EXIT WHEN NOT EXISTS (
            SELECT 1 FROM rooms WHERE code = v_code AND status IN ('open', 'in_game')
        );
    END LOOP;

    -- Create room
    v_room_id := gen_random_uuid();

    INSERT INTO rooms (
        room_id, code, owner_user_id, status, visibility,
        max_players, ruleset_id, ruleset_config, version
    ) VALUES (
        v_room_id, v_code, p_user_id, 'open'::room_status, p_visibility::room_visibility,
        p_max_players, p_ruleset_id, p_ruleset_config, 0
    );

    -- Create seat 0 (owner)
    INSERT INTO room_seats (room_id, seat_index, user_id, is_host, status, ready)
    VALUES (v_room_id, 0, p_user_id, true, 'occupied'::seat_status, 'not_ready'::ready_status);

    -- Create empty seats 1 through (max_players - 1)
    FOR i IN 1..(p_max_players - 1) LOOP
        INSERT INTO room_seats (room_id, seat_index, user_id, is_host, status, ready)
        VALUES (v_room_id, i, NULL, false, 'empty'::seat_status, 'not_ready'::ready_status);
    END LOOP;

    RETURN jsonb_build_object(
        'success', true,
        'cached', false,
        'data', jsonb_build_object(
            'room_id', v_room_id,
            'code', v_code,
            'seat_index', 0,
            'is_host', true
        )
    );
END;
$$;
