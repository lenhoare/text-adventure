from __future__ import annotations

import json
import sqlite3
from typing import Any

from engine.db import json_dumps, json_loads
from engine.events import log_event, new_id
from engine.models import SaveState
from engine.session import get_active_session


def save_game(
    conn: sqlite3.Connection,
    world_id: str,
    name: str,
    *,
    overwrite: bool = False,
) -> SaveState:
    active = get_active_session(conn, world_id)
    if not active:
        raise ValueError(f"No active session for world {world_id!r}")

    existing = conn.execute(
        "SELECT id FROM saves WHERE world_id = ? AND name = ?",
        (world_id, name),
    ).fetchone()

    if existing and not overwrite:
        raise ValueError(
            f"Save {name!r} already exists. Use --overwrite to replace it."
        )

    save_id = existing["id"] if existing else new_id("save")
    conn.execute(
        """
        INSERT INTO saves (
            id, world_id, name, current_room_id, turn,
            inventory_json, flags_json, stats_json, rng_json,
            snapshot_json, last_event_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            current_room_id = excluded.current_room_id,
            turn = excluded.turn,
            inventory_json = excluded.inventory_json,
            flags_json = excluded.flags_json,
            stats_json = excluded.stats_json,
            rng_json = excluded.rng_json,
            snapshot_json = excluded.snapshot_json,
            last_event_id = excluded.last_event_id
        """,
        (
            save_id,
            world_id,
            name,
            active.current_room_id,
            active.turn,
            json_dumps(active.inventory),
            json_dumps(active.flags),
            json_dumps(active.stats),
            json_dumps(active.rng),
            active.snapshot.model_dump_json(),
            active.last_event_id,
        ),
    )
    conn.commit()

    log_event(
        conn,
        world_id=world_id,
        save_id=active.id,
        turn=active.turn,
        event_type="save_created",
        payload={"save_id": save_id, "name": name},
    )
    return active


def export_save(conn: sqlite3.Connection, world_id: str, save_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM saves WHERE world_id = ? AND id = ?",
        (world_id, save_id),
    ).fetchone()
    if not row:
        raise ValueError(f"Save {save_id!r} not found")

    return {
        "save": {
            "id": row["id"],
            "world_id": row["world_id"],
            "name": row["name"],
            "current_room_id": row["current_room_id"],
            "turn": row["turn"],
            "inventory": json_loads(row["inventory_json"], []),
            "flags": json_loads(row["flags_json"], {}),
            "stats": json_loads(row["stats_json"], {}),
            "rng": json_loads(row["rng_json"], {}),
            "last_event_id": row["last_event_id"],
            "snapshot": json_loads(row["snapshot_json"], {}),
        }
    }
