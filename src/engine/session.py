from __future__ import annotations

import random
import sqlite3
from typing import Any

from engine.db import json_dumps, json_loads
from engine.events import log_event, new_id
from engine.models import SaveState, SessionSnapshot
from engine.world_io import find_start_room, load_world_seed


def default_rng_state(seed: int | None = None) -> dict[str, Any]:
    return {
        "algorithm": "python_random",
        "seed": seed if seed is not None else random.randint(1, 2**31 - 1),
        "draw_count": 0,
    }


class SessionError(Exception):
    pass


def get_active_session(conn: sqlite3.Connection, world_id: str) -> SaveState | None:
    row = conn.execute(
        """
        SELECT s.*
        FROM active_sessions a
        JOIN saves s ON s.id = a.save_id
        WHERE a.world_id = ?
        """,
        (world_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_save(row)


def create_session(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    name: str = "Autosave",
    seed_path: str | None = None,
) -> SaveState:
    world = conn.execute("SELECT id FROM worlds WHERE id = ?", (world_id,)).fetchone()
    if not world:
        raise SessionError(f"World {world_id!r} not found")

    start_room_id = _resolve_start_room(conn, world_id, seed_path)
    save_id = new_id("save")
    snapshot = SessionSnapshot(
        location=start_room_id,
        visited_rooms=[start_room_id],
        known_rooms=[start_room_id],
        inventory=[],
        world_revision=1,
    )
    rng_state = default_rng_state()
    conn.execute(
        """
        INSERT INTO saves (
            id, world_id, name, current_room_id, turn,
            inventory_json, flags_json, stats_json, rng_json, snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            save_id,
            world_id,
            name,
            start_room_id,
            0,
            json_dumps([]),
            json_dumps({}),
            json_dumps({}),
            json_dumps(rng_state),
            snapshot.model_dump_json(),
        ),
    )
    conn.execute(
        """
        INSERT INTO active_sessions (world_id, save_id)
        VALUES (?, ?)
        ON CONFLICT(world_id) DO UPDATE SET save_id = excluded.save_id
        """,
        (world_id, save_id),
    )
    conn.commit()

    log_event(
        conn,
        world_id=world_id,
        save_id=save_id,
        turn=0,
        event_type="session_started",
        payload={"save_id": save_id, "start_room_id": start_room_id},
    )
    return get_active_session(conn, world_id)  # type: ignore[return-value]


def load_session(conn: sqlite3.Connection, world_id: str, save_name: str) -> SaveState:
    row = conn.execute(
        """
        SELECT * FROM saves
        WHERE world_id = ? AND name = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (world_id, save_name),
    ).fetchone()
    if not row:
        raise SessionError(f"Save {save_name!r} not found for world {world_id!r}")

    conn.execute(
        """
        INSERT INTO active_sessions (world_id, save_id)
        VALUES (?, ?)
        ON CONFLICT(world_id) DO UPDATE SET save_id = excluded.save_id
        """,
        (world_id, row["id"]),
    )
    conn.commit()

    log_event(
        conn,
        world_id=world_id,
        save_id=row["id"],
        turn=row["turn"],
        event_type="session_loaded",
        payload={"save_id": row["id"], "save_name": save_name},
    )
    return _row_to_save(row)


def persist_session(conn: sqlite3.Connection, save: SaveState) -> None:
    conn.execute(
        """
        UPDATE saves SET
            current_room_id = ?,
            turn = ?,
            inventory_json = ?,
            flags_json = ?,
            stats_json = ?,
            rng_json = ?,
            snapshot_json = ?,
            last_event_id = ?
        WHERE id = ?
        """,
        (
            save.current_room_id,
            save.turn,
            json_dumps(save.inventory),
            json_dumps(save.flags),
            json_dumps(save.stats),
            json_dumps(save.rng),
            save.snapshot.model_dump_json(),
            save.last_event_id,
            save.id,
        ),
    )
    conn.commit()


def _resolve_start_room(
    conn: sqlite3.Connection, world_id: str, seed_path: str | None
) -> str:
    row = conn.execute(
        """
        SELECT id, tags_json FROM rooms
        WHERE world_id = ?
        """,
        (world_id,),
    ).fetchall()
    for room in row:
        tags = json_loads(room["tags_json"], [])
        if "starting_area" in tags:
            return room["id"]

    if seed_path:
        return find_start_room(load_world_seed(seed_path))

    raise SessionError(
        f"No starting_area room found for world {world_id!r}. "
        "Tag a room with starting_area or provide --seed-path."
    )


def _row_to_save(row: sqlite3.Row) -> SaveState:
    snapshot_data = json_loads(row["snapshot_json"], {})
    return SaveState(
        id=row["id"],
        world_id=row["world_id"],
        name=row["name"],
        current_room_id=row["current_room_id"],
        turn=row["turn"],
        inventory=json_loads(row["inventory_json"], []),
        flags=json_loads(row["flags_json"], {}),
        stats=json_loads(row["stats_json"], {}),
        rng=json_loads(row["rng_json"], {}),
        last_event_id=row["last_event_id"],
        snapshot=SessionSnapshot.model_validate(snapshot_data),
    )


def list_saves(conn: sqlite3.Connection, world_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, name, turn, current_room_id, created_at
        FROM saves
        WHERE world_id = ?
        ORDER BY created_at DESC
        """,
        (world_id,),
    ).fetchall()
    return [dict(row) for row in rows]
