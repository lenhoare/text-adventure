from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from engine.db import json_dumps, json_loads
from engine.models import ActionSeed, ItemSeed, NpcSeed, RoomSeed, WorldSeed


def find_start_room(seed: WorldSeed) -> str:
    for room_id, room in seed.rooms.items():
        if "starting_area" in room.tags:
            return room_id
    raise ValueError("No room tagged with starting_area found in world seed")


def import_world(conn: sqlite3.Connection, seed_path: Path | str) -> str:
    data = json.loads(Path(seed_path).read_text())
    seed = WorldSeed.model_validate(data)
    world_id = seed.world.id

    existing = conn.execute(
        "SELECT id FROM worlds WHERE id = ?", (world_id,)
    ).fetchone()
    if existing:
        raise ValueError(f"World {world_id!r} already exists")

    conn.execute(
        """
        INSERT INTO worlds (id, title, description, version, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            world_id,
            seed.world.title,
            seed.world.description,
            seed.world.version,
            json_dumps(seed.world.metadata),
        ),
    )

    for room in seed.rooms.values():
        insert_room(conn, world_id, room)

    for item in seed.items.values():
        insert_item(conn, world_id, item)

    for npc in seed.npcs.values():
        insert_npc(conn, world_id, npc)

    for source_room_id, actions in seed.actions.items():
        for action in actions:
            insert_action(conn, world_id, source_room_id, action)

    conn.commit()
    return world_id


def insert_room(conn: sqlite3.Connection, world_id: str, room: RoomSeed) -> None:
    conn.execute(
        """
        INSERT INTO rooms (
            id, world_id, name, region, status, description,
            coords_json, tags_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            room.id,
            world_id,
            room.name,
            room.region,
            room.status,
            room.description,
            json_dumps(room.coords.model_dump()) if room.coords else None,
            json_dumps(room.tags),
            json_dumps(room.metadata),
        ),
    )


def insert_item(conn: sqlite3.Connection, world_id: str, item: ItemSeed) -> None:
    conn.execute(
        """
        INSERT INTO items (
            id, world_id, name, description, portable, status,
            location_room_id, properties_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.id,
            world_id,
            item.name,
            item.description,
            int(item.portable),
            item.status,
            item.location,
            json_dumps(item.properties),
            json_dumps(item.metadata),
        ),
    )


def insert_npc(conn: sqlite3.Connection, world_id: str, npc: NpcSeed) -> None:
    conn.execute(
        """
        INSERT INTO npcs (
            id, world_id, name, description, location_room_id,
            status, state_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            npc.id,
            world_id,
            npc.name,
            npc.description,
            npc.location,
            npc.status,
            json_dumps(npc.state),
            json_dumps(npc.metadata),
        ),
    )


def insert_action(
    conn: sqlite3.Connection,
    world_id: str,
    source_room_id: str,
    action: ActionSeed,
) -> None:
    conn.execute(
        """
        INSERT INTO actions (
            id, world_id, source_room_id, kind, label, aliases_json,
            target_room_id, status, requires_json, effects_json,
            generator_hint, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            action.id,
            world_id,
            source_room_id,
            action.kind,
            action.label,
            json_dumps(action.aliases),
            action.target,
            action.status,
            json_dumps(action.requires),
            json_dumps(action.effects),
            action.generator_hint,
            json_dumps(action.metadata),
        ),
    )


def export_world(conn: sqlite3.Connection, world_id: str) -> dict[str, Any]:
    world_row = conn.execute(
        "SELECT * FROM worlds WHERE id = ?", (world_id,)
    ).fetchone()
    if not world_row:
        raise ValueError(f"World {world_id!r} not found")

    rooms: dict[str, Any] = {}
    for row in conn.execute(
        "SELECT * FROM rooms WHERE world_id = ? ORDER BY id", (world_id,)
    ):
        tags = json_loads(row["tags_json"], [])
        item_ids = [
            r["id"]
            for r in conn.execute(
                """
                SELECT id FROM items
                WHERE world_id = ? AND location_room_id = ? AND holder IS NULL
                ORDER BY id
                """,
                (world_id, row["id"]),
            )
        ]
        npc_ids = [
            r["id"]
            for r in conn.execute(
                """
                SELECT id FROM npcs
                WHERE world_id = ? AND location_room_id = ?
                ORDER BY id
                """,
                (world_id, row["id"]),
            )
        ]
        rooms[row["id"]] = {
            "id": row["id"],
            "name": row["name"],
            "region": row["region"],
            "status": row["status"],
            "description": row["description"],
            "coords": json_loads(row["coords_json"], None),
            "tags": tags,
            "items": item_ids,
            "npcs": npc_ids,
            "metadata": json_loads(row["metadata_json"], {}),
        }

    actions: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute(
        """
        SELECT * FROM actions
        WHERE world_id = ?
        ORDER BY source_room_id, id
        """,
        (world_id,),
    ):
        action = {
            "id": row["id"],
            "kind": row["kind"],
            "label": row["label"],
            "aliases": json_loads(row["aliases_json"], []),
            "target": row["target_room_id"],
            "status": row["status"],
            "requires": json_loads(row["requires_json"], []),
            "effects": json_loads(row["effects_json"], {}),
        }
        if row["generator_hint"]:
            action["generator_hint"] = row["generator_hint"]
        actions.setdefault(row["source_room_id"], []).append(action)

    items: dict[str, Any] = {}
    for row in conn.execute(
        "SELECT * FROM items WHERE world_id = ? ORDER BY id", (world_id,)
    ):
        items[row["id"]] = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "portable": bool(row["portable"]),
            "status": row["status"],
            "location": row["location_room_id"],
            "properties": json_loads(row["properties_json"], {}),
            "metadata": json_loads(row["metadata_json"], {}),
        }

    npcs: dict[str, Any] = {}
    for row in conn.execute(
        "SELECT * FROM npcs WHERE world_id = ? ORDER BY id", (world_id,)
    ):
        npcs[row["id"]] = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "location": row["location_room_id"],
            "status": row["status"],
            "state": json_loads(row["state_json"], {}),
            "metadata": json_loads(row["metadata_json"], {}),
        }

    return {
        "world": {
            "id": world_row["id"],
            "title": world_row["title"],
            "description": world_row["description"],
            "version": world_row["version"],
            "metadata": json_loads(world_row["metadata_json"], {}),
        },
        "rooms": rooms,
        "actions": actions,
        "items": items,
        "npcs": npcs,
    }


def load_world_seed(seed_path: Path | str) -> WorldSeed:
    data = json.loads(Path(seed_path).read_text())
    return WorldSeed.model_validate(data)
