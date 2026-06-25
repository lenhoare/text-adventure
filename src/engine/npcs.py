from __future__ import annotations

import sqlite3
from typing import Any

from engine.db import json_loads
from engine.models import SaveState


def get_merged_npc_state(
    conn: sqlite3.Connection,
    world_id: str,
    npc_id: str,
    save: SaveState,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT state_json FROM npcs WHERE world_id = ? AND id = ?",
        (world_id, npc_id),
    ).fetchone()
    base = json_loads(row["state_json"], {}) if row else {}
    overlay = save.snapshot.npc_state.get(npc_id, {})
    return {**base, **overlay}


def npc_row_to_dict(
    row: sqlite3.Row,
    *,
    save: SaveState | None = None,
    perspective: str = "player",
) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    state = json_loads(row["state_json"], {})
    if save is not None:
        state = {**state, **save.snapshot.npc_state.get(row["id"], {})}

    npc: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "state": state,
    }

    if perspective == "author":
        npc["metadata"] = metadata
        npc["topics"] = metadata.get("topics", {})
        for key in ("voice", "role", "wants", "wont"):
            if key in metadata:
                npc[key] = metadata[key]
    else:
        brief_keys = ("voice", "role")
        for key in brief_keys:
            if key in metadata:
                npc[key] = metadata[key]

    return npc


def get_npcs_in_room(
    conn: sqlite3.Connection,
    world_id: str,
    room_id: str,
    *,
    save: SaveState | None = None,
    perspective: str = "player",
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM npcs
        WHERE world_id = ? AND location_room_id = ?
        ORDER BY name
        """,
        (world_id, room_id),
    ).fetchall()
    npcs: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] == "hidden":
            continue
        npcs.append(
            npc_row_to_dict(row, save=save, perspective=perspective)
        )
    return npcs


def find_npc_match(text: str, npcs: list[dict[str, Any]]) -> dict[str, Any] | None:
    from engine.actions import find_item_match

    return find_item_match(text, npcs)


def get_npc_by_id(
    conn: sqlite3.Connection,
    world_id: str,
    npc_id: str,
    *,
    save: SaveState | None = None,
    perspective: str = "player",
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM npcs WHERE world_id = ? AND id = ?",
        (world_id, npc_id),
    ).fetchone()
    if not row:
        return None
    return npc_row_to_dict(row, save=save, perspective=perspective)
