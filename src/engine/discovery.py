from __future__ import annotations

import sqlite3
from typing import Any

from engine.db import json_loads
from engine.events import log_event
from engine.models import SaveState
from engine.requires import apply_effects, evaluate_requirements


def exit_key(source_room_id: str, action_id: str) -> str:
    return f"{source_room_id}:{action_id}"


def parse_exit_ref(ref: str | dict[str, str], default_source_room: str | None = None) -> tuple[str, str]:
    if isinstance(ref, dict):
        return ref["source_room"], ref["action_id"]
    if ":" in ref:
        source, action_id = ref.split(":", 1)
        return source, action_id
    if default_source_room is None:
        raise ValueError(f"Exit reference {ref!r} requires source room context")
    return default_source_room, ref


def is_exit_visible(
    action: dict[str, Any],
    source_room_id: str,
    save: SaveState,
) -> bool:
    status = action["status"]
    if status != "hidden":
        return status in {"committed", "blank", "blocked"}

    key = exit_key(source_room_id, action["id"])
    if key in save.snapshot.revealed_exits:
        return True

    if action.get("requires"):
        ok, _ = evaluate_requirements(
            action["requires"],
            flags=save.flags,
            inventory=save.inventory,
        )
        return ok

    return False


def get_player_room_actions(
    conn: sqlite3.Connection,
    world_id: str,
    room_id: str,
    save: SaveState,
) -> list[dict[str, Any]]:
    from engine.actions import get_room_actions

    all_actions = get_room_actions(conn, world_id, room_id, include_hidden=True)
    visible: list[dict[str, Any]] = []
    for action in all_actions:
        if action["status"] == "deprecated":
            continue
        if is_exit_visible(action, room_id, save):
            visible.append(action)
    return visible


def discover_rooms(
    conn: sqlite3.Connection,
    save: SaveState,
    room_ids: list[str],
    *,
    visited: bool = False,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for room_id in room_ids:
        row = conn.execute(
            """
            SELECT id, name, status FROM rooms
            WHERE world_id = ? AND id = ?
            """,
            (save.world_id, room_id),
        ).fetchone()
        if not row:
            continue

        newly_known = room_id not in save.snapshot.known_rooms
        if newly_known:
            save.snapshot.known_rooms.append(room_id)
            log_event(
                conn,
                world_id=save.world_id,
                save_id=save.id,
                turn=save.turn,
                event_type="room_discovered",
                payload={
                    "room_id": room_id,
                    "name": row["name"],
                    "visited": visited,
                    "world_status": row["status"],
                },
            )
            changes.append(
                {
                    "op": "discover_room",
                    "room_id": room_id,
                    "name": row["name"],
                    "visited": visited,
                }
            )

        if visited and room_id not in save.snapshot.visited_rooms:
            save.snapshot.visited_rooms.append(room_id)

    return changes


def reveal_exits(
    conn: sqlite3.Connection,
    save: SaveState,
    exit_refs: list[str | dict[str, str]],
    *,
    default_source_room: str | None = None,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for ref in exit_refs:
        source_room, action_id = parse_exit_ref(ref, default_source_room)
        key = exit_key(source_room, action_id)
        if key in save.snapshot.revealed_exits:
            continue

        row = conn.execute(
            """
            SELECT id, label, status FROM actions
            WHERE world_id = ? AND source_room_id = ? AND id = ?
            """,
            (save.world_id, source_room, action_id),
        ).fetchone()
        if not row:
            continue

        save.snapshot.revealed_exits.append(key)
        log_event(
            conn,
            world_id=save.world_id,
            save_id=save.id,
            turn=save.turn,
            event_type="exit_revealed",
            payload={
                "source_room": source_room,
                "action_id": action_id,
                "label": row["label"],
            },
        )
        changes.append(
            {
                "op": "reveal_exit",
                "source_room": source_room,
                "action_id": action_id,
            }
        )
    return changes


def discover_room_on_arrival(
    conn: sqlite3.Connection,
    save: SaveState,
    room_id: str,
) -> list[dict[str, Any]]:
    return discover_rooms(conn, save, [room_id], visited=True)


def apply_gameplay_effects(
    conn: sqlite3.Connection,
    save: SaveState,
    effects: dict[str, Any],
    *,
    default_source_room: str | None = None,
) -> list[dict[str, Any]]:
    changes = apply_effects(effects, flags=save.flags)

    discover_list = effects.get("discover_rooms")
    if isinstance(discover_list, list):
        changes.extend(
            discover_rooms(conn, save, [str(r) for r in discover_list], visited=False)
        )

    reveal_list = effects.get("reveal_exits")
    if isinstance(reveal_list, list):
        changes.extend(
            reveal_exits(
                conn,
                save,
                reveal_list,
                default_source_room=default_source_room,
            )
        )

    return changes


def get_hidden_rooms(conn: sqlite3.Connection, world_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, name, region, status, description, tags_json, coords_json
        FROM rooms
        WHERE world_id = ? AND status = 'hidden'
        ORDER BY region, id
        """,
        (world_id,),
    ).fetchall()
    rooms: list[dict[str, Any]] = []
    for row in rows:
        rooms.append(
            {
                "id": row["id"],
                "name": row["name"],
                "region": row["region"],
                "status": row["status"],
                "description": row["description"],
                "tags": json_loads(row["tags_json"], []),
                "coords": json_loads(row["coords_json"], None),
            }
        )
    return rooms


def get_hidden_exits(conn: sqlite3.Connection, world_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT source_room_id, id, label, target_room_id, requires_json, generator_hint
        FROM actions
        WHERE world_id = ? AND status = 'hidden'
        ORDER BY source_room_id, id
        """,
        (world_id,),
    ).fetchall()
    exits: list[dict[str, Any]] = []
    for row in rows:
        exits.append(
            {
                "source_room": row["source_room_id"],
                "id": row["id"],
                "label": row["label"],
                "target": row["target_room_id"],
                "requires": json_loads(row["requires_json"], []),
                "generator_hint": row["generator_hint"],
            }
        )
    return exits
