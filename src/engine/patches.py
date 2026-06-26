from __future__ import annotations

import sqlite3
from typing import Any

from engine.db import json_dumps, json_loads
from engine.events import log_event
from engine.models import ActionSeed, Coords, ItemSeed, NpcSeed, RoomSeed
from engine.session import get_active_session, persist_session
from engine.world_io import insert_action, insert_item, insert_npc, insert_room


class PatchError(Exception):
    pass


class PatchValidationError(PatchError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def apply_patch(
    conn: sqlite3.Connection,
    patch_data: dict[str, Any],
    *,
    save_id: str | None = None,
) -> dict[str, Any]:
    patch = patch_data.get("patch", patch_data)
    patch_id = patch.get("id", "patch_unknown")
    world_id = patch["world_id"]
    author = patch.get("author", "system")
    source_turn = patch.get("source_turn")
    ops = patch.get("ops", [])

    applied = apply_ops(conn, world_id, ops, save_id=save_id)

    conn.execute(
        """
        UPDATE worlds SET version = version + 1, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (world_id,),
    )
    conn.commit()

    save = get_active_session(conn, world_id)
    if save:
        save.snapshot.world_revision += 1
        persist_session(conn, save)

    event_id = log_event(
        conn,
        world_id=world_id,
        save_id=save_id or (save.id if save else None),
        turn=source_turn or (save.turn if save else 0),
        event_type="patch_committed",
        payload={
            "patch_id": patch_id,
            "author": author,
            "ops": applied,
        },
    )

    return {
        "ok": True,
        "patch_id": patch_id,
        "ops_applied": applied,
        "validation_errors": [],
        "event_id": event_id,
    }


def apply_ops(
    conn: sqlite3.Connection,
    world_id: str,
    ops: list[dict[str, Any]],
    *,
    save_id: str | None = None,
) -> list[str]:
    errors = validate_patch(conn, world_id, ops)
    if errors:
        raise PatchValidationError(errors)

    applied: list[str] = []
    for op in ops:
        op_name = op["op"]
        _apply_op(conn, world_id, op, save_id=save_id)
        applied.append(op_name)
    conn.commit()
    return applied


def validate_patch(
    conn: sqlite3.Connection, world_id: str, ops: list[dict[str, Any]]
) -> list[str]:
    errors: list[str] = []
    pending_rooms: set[str] = set()
    pending_items: set[str] = set()
    pending_npcs: set[str] = set()

    for op in ops:
        name = op.get("op")
        if name == "add_room":
            errors.extend(_validate_add_room(conn, world_id, op, pending_rooms))
        elif name == "update_room":
            errors.extend(_validate_update_room(conn, world_id, op, pending_rooms))
        elif name == "add_exit":
            errors.extend(_validate_add_exit(conn, world_id, op, pending_rooms))
        elif name == "update_exit":
            errors.extend(_validate_update_exit(conn, world_id, op, pending_rooms))
        elif name == "add_item":
            errors.extend(
                _validate_add_item(conn, world_id, op, pending_items, pending_rooms)
            )
        elif name == "add_npc":
            errors.extend(
                _validate_add_npc(conn, world_id, op, pending_npcs, pending_rooms)
            )
        elif name == "move_item":
            errors.extend(_validate_move_item(conn, world_id, op, pending_rooms))
        elif name in {"set_flag", "clear_flag"}:
            continue
        elif name == "add_draft":
            if "payload" not in op:
                errors.append("add_draft requires payload")
        elif name == "commit_draft":
            draft_id = op.get("draft_id")
            if not draft_id:
                errors.append("commit_draft requires draft_id")
            else:
                row = conn.execute(
                    "SELECT status FROM drafts WHERE id = ?", (draft_id,)
                ).fetchone()
                if not row:
                    errors.append(f"commit_draft target {draft_id!r} not found")
                elif row["status"] != "active":
                    errors.append(f"commit_draft target {draft_id!r} is not active")
        elif name == "reject_draft":
            draft_id = op.get("draft_id")
            if not draft_id:
                errors.append("reject_draft requires draft_id")
            else:
                row = conn.execute(
                    "SELECT status FROM drafts WHERE id = ?", (draft_id,)
                ).fetchone()
                if not row:
                    errors.append(f"reject_draft target {draft_id!r} not found")
                elif row["status"] != "active":
                    errors.append(f"reject_draft target {draft_id!r} is not active")
        elif name == "batch_add_region":
            errors.extend(_validate_batch_add_region(conn, world_id, op))
        else:
            errors.append(f"Unknown patch op: {name!r}")

    return errors


def _room_exists(
    conn: sqlite3.Connection,
    world_id: str,
    room_id: str,
    pending: set[str],
) -> bool:
    if room_id in pending:
        return True
    row = conn.execute(
        "SELECT 1 FROM rooms WHERE world_id = ? AND id = ?",
        (world_id, room_id),
    ).fetchone()
    return row is not None


def _validate_add_room(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
) -> list[str]:
    errors: list[str] = []
    room_id = op.get("room_id")
    payload = op.get("payload", {})
    if not room_id:
        errors.append("add_room requires room_id")
        return errors
    if _room_exists(conn, world_id, room_id, pending):
        errors.append(f"room id {room_id!r} already exists")
    for field in ("name", "description", "status", "region"):
        if field not in payload:
            errors.append(f"add_room payload missing {field}")
    pending.add(room_id)
    return errors


def _validate_update_room(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
) -> list[str]:
    room_id = op.get("room_id")
    if not room_id:
        return ["update_room requires room_id"]
    if not _room_exists(conn, world_id, room_id, pending):
        return [f"update_room target {room_id!r} does not exist"]
    return []


def _validate_add_exit(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
) -> list[str]:
    errors: list[str] = []
    source_room = op.get("source_room")
    action_id = op.get("action_id")
    payload = op.get("payload", {})
    if not source_room or not action_id:
        return ["add_exit requires source_room and action_id"]
    if not _room_exists(conn, world_id, source_room, pending):
        errors.append(f"add_exit source room {source_room!r} does not exist")
    existing = conn.execute(
        """
        SELECT 1 FROM actions
        WHERE world_id = ? AND source_room_id = ? AND id = ?
        """,
        (world_id, source_room, action_id),
    ).fetchone()
    if existing:
        errors.append(f"action id {action_id!r} already exists in {source_room!r}")
    for field in ("kind", "label", "aliases"):
        if field not in payload:
            errors.append(f"add_exit payload missing {field}")
    target = payload.get("target")
    if target is not None and not _room_exists(conn, world_id, target, pending):
        errors.append(f"add_exit target room {target!r} does not exist")
    return errors


def _validate_update_exit(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
) -> list[str]:
    source_room = op.get("source_room")
    action_id = op.get("action_id")
    if not source_room or not action_id:
        return ["update_exit requires source_room and action_id"]
    row = conn.execute(
        """
        SELECT 1 FROM actions
        WHERE world_id = ? AND source_room_id = ? AND id = ?
        """,
        (world_id, source_room, action_id),
    ).fetchone()
    if not row:
        return [f"update_exit action {action_id!r} not found in {source_room!r}"]
    target = op.get("payload", {}).get("target")
    if target is not None and not _room_exists(conn, world_id, target, pending):
        return [f"update_exit target room {target!r} does not exist"]
    return []


def _validate_add_item(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
    pending_rooms: set[str],
) -> list[str]:
    errors: list[str] = []
    item_id = op.get("item_id")
    payload = op.get("payload", {})
    if not item_id:
        return ["add_item requires item_id"]
    if item_id in pending:
        errors.append(f"item id {item_id!r} duplicated in patch")
        return errors
    row = conn.execute(
        "SELECT 1 FROM items WHERE world_id = ? AND id = ?",
        (world_id, item_id),
    ).fetchone()
    if row:
        errors.append(f"item id {item_id!r} already exists")
    for field in ("name", "description"):
        if field not in payload:
            errors.append(f"add_item payload missing {field}")
    if "portable" not in payload:
        errors.append("add_item payload missing portable")
    location = payload.get("location")
    if location and not _room_exists(conn, world_id, location, pending_rooms):
        errors.append(f"add_item location room {location!r} does not exist")
    pending.add(item_id)
    return errors


def _validate_add_npc(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
    pending_rooms: set[str],
) -> list[str]:
    errors: list[str] = []
    npc_id = op.get("npc_id")
    payload = op.get("payload", {})
    if not npc_id:
        return ["add_npc requires npc_id"]
    if npc_id in pending:
        errors.append(f"npc id {npc_id!r} duplicated in patch")
        return errors
    row = conn.execute(
        "SELECT 1 FROM npcs WHERE world_id = ? AND id = ?",
        (world_id, npc_id),
    ).fetchone()
    if row:
        errors.append(f"npc id {npc_id!r} already exists")
    for field in ("name", "description"):
        if field not in payload:
            errors.append(f"add_npc payload missing {field}")
    location = payload.get("location")
    if location and not _room_exists(conn, world_id, location, pending_rooms):
        errors.append(f"add_npc location room {location!r} does not exist")
    pending.add(npc_id)
    return errors


def _validate_move_item(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    pending: set[str],
) -> list[str]:
    item_id = op.get("item_id")
    to = op.get("to")
    if not item_id or to is None:
        return ["move_item requires item_id and to"]
    row = conn.execute(
        "SELECT 1 FROM items WHERE world_id = ? AND id = ?",
        (world_id, item_id),
    ).fetchone()
    if not row and item_id not in pending:
        return [f"move_item item {item_id!r} does not exist"]
    if to != "inventory" and not _room_exists(conn, world_id, to, pending):
        return [f"move_item destination {to!r} does not exist"]
    return []


def _validate_batch_add_region(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> list[str]:
    payload = op.get("payload", {})
    default_room_status = payload.get("default_room_status", "committed")
    default_exit_status = payload.get("default_exit_status", "committed")
    errors: list[str] = []
    pending_rooms: set[str] = set()
    pending_items: set[str] = set()
    for room_id, room_data in payload.get("rooms", {}).items():
        room_payload = dict(room_data)
        room_payload.setdefault("status", default_room_status)
        errors.extend(
            _validate_add_room(
                conn,
                world_id,
                {"room_id": room_id, "payload": room_payload},
                pending_rooms,
            )
        )
    for item_id, item_data in payload.get("items", {}).items():
        errors.extend(
            _validate_add_item(
                conn,
                world_id,
                {"item_id": item_id, "payload": item_data},
                pending_items,
                pending_rooms,
            )
        )
    for source_room, actions in payload.get("actions", {}).items():
        for action in actions:
            action_id = action.get("id")
            action_payload = dict(action)
            action_payload.setdefault("status", default_exit_status)
            errors.extend(
                _validate_add_exit(
                    conn,
                    world_id,
                    {
                        "source_room": source_room,
                        "action_id": action_id,
                        "payload": action_payload,
                    },
                    pending_rooms,
                )
            )
    return errors


def _apply_op(
    conn: sqlite3.Connection,
    world_id: str,
    op: dict[str, Any],
    *,
    save_id: str | None,
) -> None:
    name = op["op"]
    if name == "add_room":
        _apply_add_room(conn, world_id, op)
    elif name == "update_room":
        _apply_update_room(conn, world_id, op)
    elif name == "add_exit":
        _apply_add_exit(conn, world_id, op)
    elif name == "update_exit":
        _apply_update_exit(conn, world_id, op)
    elif name == "add_item":
        _apply_add_item(conn, world_id, op)
    elif name == "add_npc":
        _apply_add_npc(conn, world_id, op)
    elif name == "move_item":
        _apply_move_item(conn, world_id, op)
    elif name == "set_flag":
        _apply_set_flag(conn, world_id, op)
    elif name == "clear_flag":
        _apply_clear_flag(conn, world_id, op)
    elif name == "add_draft":
        from engine.drafts import create_draft_from_payload

        create_draft_from_payload(conn, world_id, op["payload"], save_id=save_id)
    elif name == "commit_draft":
        from engine.drafts import commit_draft

        commit_draft(
            conn,
            world_id,
            op["draft_id"],
            save_id=save_id,
            manage_revision=False,
        )
    elif name == "reject_draft":
        from engine.drafts import reject_draft

        reject_draft(conn, world_id, op["draft_id"], save_id=save_id)
    elif name == "batch_add_region":
        _apply_batch_add_region(conn, world_id, op)
    else:
        raise PatchError(f"Unknown op {name!r}")


def _apply_add_room(conn: sqlite3.Connection, world_id: str, op: dict[str, Any]) -> None:
    room_id = op["room_id"]
    payload = op["payload"]
    coords = payload.get("coords")
    if coords is not None and isinstance(coords, dict):
        coords = Coords.model_validate(coords)
    room = RoomSeed(
        id=room_id,
        name=payload["name"],
        region=payload["region"],
        status=payload["status"],
        description=payload["description"],
        coords=coords,
        tags=payload.get("tags", []),
        metadata=payload.get("metadata", {}),
    )
    insert_room(conn, world_id, room)


def _apply_update_room(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    room_id = op["room_id"]
    payload = op["payload"]
    row = conn.execute(
        "SELECT * FROM rooms WHERE world_id = ? AND id = ?",
        (world_id, room_id),
    ).fetchone()
    if not row:
        raise PatchError(f"Room {room_id!r} not found")

    fields = {
        "name": payload.get("name", row["name"]),
        "region": payload.get("region", row["region"]),
        "status": payload.get("status", row["status"]),
        "description": payload.get("description", row["description"]),
        "coords_json": json_dumps(payload["coords"])
        if "coords" in payload
        else row["coords_json"],
        "tags_json": json_dumps(payload.get("tags", json_loads(row["tags_json"], []))),
        "metadata_json": json_dumps(
            payload.get("metadata", json_loads(row["metadata_json"], {}))
        ),
    }
    conn.execute(
        """
        UPDATE rooms SET
            name = ?, region = ?, status = ?, description = ?,
            coords_json = ?, tags_json = ?, metadata_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE world_id = ? AND id = ?
        """,
        (
            fields["name"],
            fields["region"],
            fields["status"],
            fields["description"],
            fields["coords_json"],
            fields["tags_json"],
            fields["metadata_json"],
            world_id,
            room_id,
        ),
    )


def _apply_add_exit(conn: sqlite3.Connection, world_id: str, op: dict[str, Any]) -> None:
    payload = op["payload"]
    action = ActionSeed(
        id=op["action_id"],
        kind=payload["kind"],
        label=payload["label"],
        aliases=payload.get("aliases", []),
        target=payload.get("target"),
        status=payload.get("status", "committed"),
        requires=payload.get("requires", []),
        effects=payload.get("effects", {}),
        generator_hint=payload.get("generator_hint"),
        metadata=payload.get("metadata", {}),
    )
    insert_action(conn, world_id, op["source_room"], action)


def _apply_update_exit(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    source_room = op["source_room"]
    action_id = op["action_id"]
    payload = op["payload"]
    row = conn.execute(
        """
        SELECT * FROM actions
        WHERE world_id = ? AND source_room_id = ? AND id = ?
        """,
        (world_id, source_room, action_id),
    ).fetchone()
    if not row:
        raise PatchError(f"Action {action_id!r} not found")

    old_aliases = json_loads(row["aliases_json"], [])
    new_aliases = payload.get("aliases", old_aliases)
    merged_aliases = list(dict.fromkeys([*old_aliases, *new_aliases]))

    conn.execute(
        """
        UPDATE actions SET
            kind = ?,
            label = ?,
            aliases_json = ?,
            target_room_id = ?,
            status = ?,
            requires_json = ?,
            effects_json = ?,
            generator_hint = ?
        WHERE world_id = ? AND source_room_id = ? AND id = ?
        """,
        (
            payload.get("kind", row["kind"]),
            payload.get("label", row["label"]),
            json_dumps(merged_aliases),
            payload.get("target", row["target_room_id"]),
            payload.get("status", row["status"]),
            json_dumps(payload.get("requires", json_loads(row["requires_json"], []))),
            json_dumps(payload.get("effects", json_loads(row["effects_json"], {}))),
            payload.get("generator_hint", row["generator_hint"]),
            world_id,
            source_room,
            action_id,
        ),
    )


def _apply_add_item(conn: sqlite3.Connection, world_id: str, op: dict[str, Any]) -> None:
    payload = op["payload"]
    item = ItemSeed(
        id=op["item_id"],
        name=payload["name"],
        description=payload["description"],
        portable=payload["portable"],
        status=payload.get("status", "committed"),
        location=payload.get("location"),
        properties=payload.get("properties", {}),
        metadata=payload.get("metadata", {}),
    )
    insert_item(conn, world_id, item)


def _apply_add_npc(conn: sqlite3.Connection, world_id: str, op: dict[str, Any]) -> None:
    payload = op["payload"]
    npc = NpcSeed(
        id=op["npc_id"],
        name=payload["name"],
        description=payload["description"],
        location=payload.get("location"),
        status=payload.get("status", "committed"),
        state=payload.get("state", {}),
        metadata=payload.get("metadata", {}),
    )
    insert_npc(conn, world_id, npc)


def _apply_move_item(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    item_id = op["item_id"]
    to = op["to"]
    if to == "inventory":
        conn.execute(
            """
            UPDATE items SET location_room_id = NULL, holder = 'player'
            WHERE world_id = ? AND id = ?
            """,
            (world_id, item_id),
        )
        save = get_active_session(conn, world_id)
        if save and item_id not in save.inventory:
            save.inventory.append(item_id)
            persist_session(conn, save)
    else:
        conn.execute(
            """
            UPDATE items SET location_room_id = ?, holder = NULL
            WHERE world_id = ? AND id = ?
            """,
            (to, world_id, item_id),
        )
        save = get_active_session(conn, world_id)
        if save and item_id in save.inventory:
            save.inventory.remove(item_id)
            persist_session(conn, save)


def _apply_set_flag(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    save = get_active_session(conn, world_id)
    if not save:
        return
    save.flags[op["flag"]] = op.get("value", True)
    persist_session(conn, save)


def _apply_clear_flag(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    save = get_active_session(conn, world_id)
    if not save:
        return
    save.flags.pop(op["flag"], None)
    persist_session(conn, save)


def _apply_batch_add_region(
    conn: sqlite3.Connection, world_id: str, op: dict[str, Any]
) -> None:
    payload = op["payload"]
    default_room_status = payload.get("default_room_status", "committed")
    default_exit_status = payload.get("default_exit_status", "committed")

    for room_id, room_data in payload.get("rooms", {}).items():
        room_payload = dict(room_data)
        room_payload.setdefault("status", default_room_status)
        _apply_add_room(
            conn, world_id, {"room_id": room_id, "payload": room_payload}
        )
    for item_id, item_data in payload.get("items", {}).items():
        _apply_add_item(conn, world_id, {"item_id": item_id, "payload": item_data})
    for source_room, actions in payload.get("actions", {}).items():
        for action in actions:
            action_id = action["id"]
            action_payload = {
                k: v for k, v in action.items() if k != "id"
            }
            action_payload.setdefault("status", default_exit_status)
            _apply_add_exit(
                conn,
                world_id,
                {
                    "source_room": source_room,
                    "action_id": action_id,
                    "payload": action_payload,
                },
            )


def find_blank_movement_exit(
    conn: sqlite3.Connection, world_id: str, source_room_id: str
) -> str | None:
    row = conn.execute(
        """
        SELECT id FROM actions
        WHERE world_id = ? AND source_room_id = ?
          AND kind = 'movement' AND status = 'blank'
        ORDER BY id
        LIMIT 1
        """,
        (world_id, source_room_id),
    ).fetchone()
    return row["id"] if row else None


def draft_payload_to_ops(
    conn: sqlite3.Connection, world_id: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    ops: list[dict[str, Any]] = []
    room = payload.get("room")
    if room:
        room_id = room["id"]
        ops.append(
            {
                "op": "add_room",
                "room_id": room_id,
                "payload": {k: v for k, v in room.items() if k != "id"},
            }
        )

    blank_consumed: set[str] = set()
    for entry in payload.get("actions", []):
        source_room = entry["source_room"]
        action = entry["action"]
        blank_id = payload.get("replace_blank_action_id")
        if not blank_id:
            blank_id = find_blank_movement_exit(conn, world_id, source_room)
        if blank_id and blank_id not in blank_consumed and action.get("kind") == "movement":
            blank_consumed.add(blank_id)
            ops.append(
                {
                    "op": "update_exit",
                    "source_room": source_room,
                    "action_id": blank_id,
                    "payload": {
                        "kind": action["kind"],
                        "label": action["label"],
                        "aliases": action.get("aliases", []),
                        "target": action.get("target"),
                        "status": action.get("status", "committed"),
                        "requires": action.get("requires", []),
                        "effects": action.get("effects", {}),
                    },
                }
            )
        else:
            ops.append(
                {
                    "op": "add_exit",
                    "source_room": source_room,
                    "action_id": action["id"],
                    "payload": {
                        k: v
                        for k, v in action.items()
                        if k not in {"id", "return_action"}
                    },
                }
            )

    for item_id, item_data in payload.get("items", {}).items():
        ops.append(
            {
                "op": "add_item",
                "item_id": item_id,
                "payload": {k: v for k, v in item_data.items() if k != "id"},
            }
        )

    return ops
