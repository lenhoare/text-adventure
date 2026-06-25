from __future__ import annotations

import sqlite3
from typing import Any

from engine.actions import get_items_in_room, get_room_actions
from engine.db import json_loads
from engine.events import get_recent_events
from engine.models import AgentContext
from engine.session import get_active_session


def build_agent_context(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    recent_event_limit: int = 10,
    player_input: str | None = None,
) -> AgentContext:
    save = get_active_session(conn, world_id)
    if not save:
        raise ValueError(f"No active session for world {world_id!r}")

    room = _get_room(conn, world_id, save.current_room_id)
    if not room:
        raise ValueError(f"Current room {save.current_room_id!r} not found")

    all_actions = get_room_actions(conn, world_id, save.current_room_id)
    visible_exits = [
        a for a in all_actions if a["kind"] == "movement" and a["status"] != "hidden"
    ]
    available_actions = [
        a for a in all_actions if a["status"] in {"committed", "blank", "blocked"}
    ]

    visible_items = get_items_in_room(conn, world_id, save.current_room_id)
    visible_npcs = _get_npcs_in_room(conn, world_id, save.current_room_id)
    inventory_items = [
        item
        for item_id in save.inventory
        if (item := _get_item(conn, world_id, item_id))
    ]

    candidate_actions: list[dict[str, Any]] = []
    if player_input:
        from engine.actions import find_candidate_actions

        candidate_actions = [
            {"id": a["id"], "label": a["label"], "kind": a["kind"]}
            for a in find_candidate_actions(player_input, all_actions)
        ]

    return AgentContext(
        world_id=world_id,
        save_id=save.id,
        turn=save.turn,
        current_room=room,
        visible_exits=visible_exits,
        visible_items=visible_items,
        visible_npcs=visible_npcs,
        inventory=inventory_items,
        flags=save.flags,
        stats=save.stats,
        recent_events=get_recent_events(
            conn, world_id, limit=recent_event_limit, save_id=save.id
        ),
        available_actions=available_actions,
        candidate_actions=candidate_actions,
    )


def render_map(conn: sqlite3.Connection, world_id: str) -> str:
    save = get_active_session(conn, world_id)
    if not save:
        raise ValueError(f"No active session for world {world_id!r}")

    known = set(save.snapshot.known_rooms)
    rows = conn.execute(
        """
        SELECT id, name, region, coords_json, status
        FROM rooms
        WHERE world_id = ?
        ORDER BY region, id
        """,
        (world_id,),
    ).fetchall()

    lines = [f"Known rooms ({len(known)}):"]
    for row in rows:
        if row["id"] not in known and row["status"] == "hidden":
            continue
        marker = "*" if row["id"] == save.current_room_id else " "
        visited = "visited" if row["id"] in save.snapshot.visited_rooms else "known"
        coords = json_loads(row["coords_json"], None)
        coord_text = ""
        if coords:
            coord_text = f" ({coords.get('x', 0)},{coords.get('y', 0)})"
        lines.append(
            f"{marker} {row['id']}: {row['name']}{coord_text} [{visited}]"
        )
    return "\n".join(lines)


def _get_room(
    conn: sqlite3.Connection, world_id: str, room_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM rooms WHERE world_id = ? AND id = ?",
        (world_id, room_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "region": row["region"],
        "status": row["status"],
        "description": row["description"],
        "tags": json_loads(row["tags_json"], []),
        "coords": json_loads(row["coords_json"], None),
        "metadata": json_loads(row["metadata_json"], {}),
    }


def _get_item(
    conn: sqlite3.Connection, world_id: str, item_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM items WHERE world_id = ? AND id = ?",
        (world_id, item_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "portable": bool(row["portable"]),
        "properties": json_loads(row["properties_json"], {}),
    }


def _get_npcs_in_room(
    conn: sqlite3.Connection, world_id: str, room_id: str
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
            {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "state": json_loads(row["state_json"], {}),
            }
        )
    return npcs
