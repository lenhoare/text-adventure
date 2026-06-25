from __future__ import annotations

import sqlite3
from typing import Any, Literal

from engine.drafts import list_drafts
from engine.actions import get_items_in_room
from engine.db import json_loads
from engine.discovery import (
    get_hidden_exits,
    get_hidden_rooms,
    get_player_room_actions,
)
from engine.events import get_recent_events
from engine.models import AgentContext
from engine.session import get_active_session


def build_agent_context(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    recent_event_limit: int = 10,
    player_input: str | None = None,
    perspective: Literal["player", "author"] = "player",
) -> AgentContext:
    save = get_active_session(conn, world_id)
    if not save:
        raise ValueError(f"No active session for world {world_id!r}")

    room = _get_room(conn, world_id, save.current_room_id)
    if not room:
        raise ValueError(f"Current room {save.current_room_id!r} not found")

    player_actions = get_player_room_actions(
        conn, world_id, save.current_room_id, save
    )
    visible_exits = [a for a in player_actions if a["kind"] == "movement"]
    available_actions = [
        a for a in player_actions if a["status"] in {"committed", "blank", "blocked", "hidden"}
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
            for a in find_candidate_actions(player_input, player_actions)
        ]

    known_rooms = _known_room_details(conn, world_id, save)

    hidden_rooms: list[dict[str, Any]] = []
    hidden_exits: list[dict[str, Any]] = []
    if perspective == "author":
        player_known = set(save.snapshot.known_rooms)
        hidden_rooms = [
            room
            for room in get_hidden_rooms(conn, world_id)
            if room["id"] not in player_known
        ]
        hidden_exits = get_hidden_exits(conn, world_id)

    return AgentContext(
        perspective=perspective,
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
        known_rooms=known_rooms,
        recent_events=get_recent_events(
            conn, world_id, limit=recent_event_limit, save_id=save.id
        ),
        available_actions=available_actions,
        candidate_actions=candidate_actions,
        active_drafts=list_drafts(conn, world_id, status="active"),
        hidden_rooms=hidden_rooms,
        hidden_exits=hidden_exits,
    )


def _known_room_details(
    conn: sqlite3.Connection, world_id: str, save
) -> list[dict[str, Any]]:
    rooms: list[dict[str, Any]] = []
    visited = set(save.snapshot.visited_rooms)
    for room_id in save.snapshot.known_rooms:
        row = conn.execute(
            """
            SELECT id, name, region, status
            FROM rooms WHERE world_id = ? AND id = ?
            """,
            (world_id, room_id),
        ).fetchone()
        if not row:
            continue
        rooms.append(
            {
                "id": row["id"],
                "name": row["name"],
                "region": row["region"],
                "visited": room_id in visited,
            }
        )
    return rooms


def render_map(conn: sqlite3.Connection, world_id: str) -> str:
    save = get_active_session(conn, world_id)
    if not save:
        raise ValueError(f"No active session for world {world_id!r}")

    known = save.snapshot.known_rooms
    visited = set(save.snapshot.visited_rooms)

    lines = [f"Known rooms ({len(known)}):"]
    if not known:
        lines.append("  (none yet)")
        return "\n".join(lines)

    rows = conn.execute(
        """
        SELECT id, name, region, coords_json
        FROM rooms
        WHERE world_id = ? AND id IN ({})
        ORDER BY region, id
        """.format(",".join("?" for _ in known)),
        (world_id, *known),
    ).fetchall()
    for row in rows:
        marker = "*" if row["id"] == save.current_room_id else " "
        state = "visited" if row["id"] in visited else "known"
        coords = json_loads(row["coords_json"], None) if row["coords_json"] else None
        coord_text = ""
        if coords:
            coord_text = f" ({coords.get('x', 0)},{coords.get('y', 0)})"
        lines.append(
            f"{marker} {row['id']}: {row['name']}{coord_text} [{state}]"
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
