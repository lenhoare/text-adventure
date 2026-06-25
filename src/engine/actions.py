from __future__ import annotations

import sqlite3
from typing import Any

from engine.db import json_loads
from engine.events import log_event, log_transcript
from engine.models import PlayResult, SaveState
from engine.requires import apply_effects, evaluate_requirements
from engine.session import persist_session


def normalize_input(text: str) -> str:
    return " ".join(text.strip().lower().split())


def get_room_actions(
    conn: sqlite3.Connection,
    world_id: str,
    room_id: str,
    *,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    statuses = ("committed", "blank", "blocked")
    if include_hidden:
        statuses = ("committed", "blank", "blocked", "hidden")

    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"""
        SELECT * FROM actions
        WHERE world_id = ? AND source_room_id = ?
          AND status IN ({placeholders})
        ORDER BY id
        """,
        (world_id, room_id, *statuses),
    ).fetchall()

    actions: list[dict[str, Any]] = []
    for row in rows:
        actions.append(_action_row_to_dict(row))
    return actions


def _action_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "label": row["label"],
        "aliases": json_loads(row["aliases_json"], []),
        "target": row["target_room_id"],
        "status": row["status"],
        "requires": json_loads(row["requires_json"], []),
        "effects": json_loads(row["effects_json"], {}),
        "generator_hint": row["generator_hint"],
    }


def match_action(text: str, actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = normalize_input(text)
    if not normalized:
        return None

    best: dict[str, Any] | None = None
    best_len = -1
    for action in actions:
        candidates = [action["label"], *action["aliases"]]
        for candidate in candidates:
            candidate_norm = normalize_input(candidate)
            if normalized == candidate_norm and len(candidate_norm) > best_len:
                best = action
                best_len = len(candidate_norm)
    return best


def find_candidate_actions(
    text: str, actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized = normalize_input(text)
    if not normalized:
        return []

    candidates: list[dict[str, Any]] = []
    for action in actions:
        labels = [action["label"], *action["aliases"]]
        for label in labels:
            label_norm = normalize_input(label)
            if normalized in label_norm or label_norm in normalized:
                candidates.append(action)
                break
    return candidates


def get_items_in_room(
    conn: sqlite3.Connection, world_id: str, room_id: str
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM items
        WHERE world_id = ? AND location_room_id = ? AND holder IS NULL
        ORDER BY name
        """,
        (world_id, room_id),
    ).fetchall()
    return [_item_row_to_dict(row) for row in rows]


def get_item_by_id(
    conn: sqlite3.Connection, world_id: str, item_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM items WHERE world_id = ? AND id = ?",
        (world_id, item_id),
    ).fetchone()
    return _item_row_to_dict(row) if row else None


def find_item_match(text: str, items: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = normalize_input(text)
    if not normalized:
        return None

    best: dict[str, Any] | None = None
    best_len = -1
    for item in items:
        for candidate in (item["name"], item["id"]):
            candidate_norm = normalize_input(candidate)
            if candidate_norm in normalized or normalized in candidate_norm:
                if len(candidate_norm) > best_len:
                    best = item
                    best_len = len(candidate_norm)
    return best


def _item_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "portable": bool(row["portable"]),
        "status": row["status"],
        "location": row["location_room_id"],
        "properties": json_loads(row["properties_json"], {}),
    }


def play(
    conn: sqlite3.Connection,
    save: SaveState,
    player_input: str,
) -> PlayResult:
    save.turn += 1
    turn = save.turn
    world_id = save.world_id
    room_id = save.current_room_id

    log_event(
        conn,
        world_id=world_id,
        save_id=save.id,
        turn=turn,
        event_type="player_input",
        payload={"text": player_input},
    )
    log_transcript(
        conn,
        world_id=world_id,
        save_id=save.id,
        turn=turn,
        speaker="player",
        text=player_input,
    )

    normalized = normalize_input(player_input)
    room_actions = get_room_actions(conn, world_id, room_id)
    room_items = get_items_in_room(conn, world_id, room_id)

    if normalized in {"look", "l"}:
        result = _handle_look(conn, save, room_items)
    elif normalized in {"inventory", "inv", "i"}:
        result = _handle_inventory(save)
    elif normalized.startswith("examine ") or normalized.startswith("x "):
        target = player_input.split(" ", 1)[1] if " " in player_input else ""
        result = _handle_examine(conn, save, target, room_items)
    elif normalized.startswith("take ") or normalized.startswith("get "):
        target = player_input.split(" ", 1)[1] if " " in player_input else ""
        result = _handle_take(conn, save, target, room_items)
    elif normalized.startswith("drop "):
        target = player_input.split(" ", 1)[1] if " " in player_input else ""
        result = _handle_drop(conn, save, target)
    else:
        matched = match_action(player_input, room_actions)
        if matched:
            if matched["kind"] == "movement":
                result = _handle_movement(conn, save, matched)
            else:
                result = _handle_interaction(conn, save, matched)
        else:
            candidates = find_candidate_actions(player_input, room_actions)
            result = PlayResult(
                ok=False,
                message="Could not parse input against known actions.",
                turn=turn,
                requires_agent=True,
                candidate_actions=[
                    {"id": a["id"], "label": a["label"], "kind": a["kind"]}
                    for a in candidates
                ],
            )

    if result.ok:
        log_transcript(
            conn,
            world_id=world_id,
            save_id=save.id,
            turn=turn,
            speaker="engine",
            text=result.message,
        )
    else:
        log_event(
            conn,
            world_id=world_id,
            save_id=save.id,
            turn=turn,
            event_type="unresolved_input",
            payload={
                "text": player_input,
                "candidate_actions": result.candidate_actions,
            },
        )

    persist_session(conn, save)
    return result


def _handle_look(
    conn: sqlite3.Connection, save: SaveState, room_items: list[dict[str, Any]]
) -> PlayResult:
    room = _get_room(conn, save.world_id, save.current_room_id)
    exits = [
        a
        for a in get_room_actions(conn, save.world_id, save.current_room_id)
        if a["kind"] == "movement" and a["status"] != "hidden"
    ]
    lines = [room["description"]]
    if exits:
        exit_labels = ", ".join(a["label"] for a in exits)
        lines.append(f"Exits: {exit_labels}")
    if room_items:
        item_names = ", ".join(i["name"] for i in room_items)
        lines.append(f"You see: {item_names}")
    return PlayResult(
        ok=True,
        message="\n".join(lines),
        turn=save.turn,
        parsed_action="look",
    )


def _handle_inventory(save: SaveState) -> PlayResult:
    if not save.inventory:
        message = "You are carrying nothing."
    else:
        message = "You are carrying: " + ", ".join(save.inventory)
    return PlayResult(
        ok=True,
        message=message,
        turn=save.turn,
        parsed_action="inventory",
    )


def _handle_examine(
    conn: sqlite3.Connection,
    save: SaveState,
    target: str,
    room_items: list[dict[str, Any]],
) -> PlayResult:
    item = find_item_match(target, room_items)
    if not item:
        inv_items = [
            get_item_by_id(conn, save.world_id, item_id)
            for item_id in save.inventory
        ]
        inv_items = [i for i in inv_items if i]
        item = find_item_match(target, inv_items)

    if not item:
        return PlayResult(
            ok=False,
            message=f"You don't see {target!r} here.",
            turn=save.turn,
            parsed_action="examine",
            requires_agent=True,
        )

    return PlayResult(
        ok=True,
        message=item["description"],
        turn=save.turn,
        parsed_action="examine",
        parsed_action_id=item["id"],
    )


def _handle_take(
    conn: sqlite3.Connection,
    save: SaveState,
    target: str,
    room_items: list[dict[str, Any]],
) -> PlayResult:
    item = find_item_match(target, room_items)
    if not item:
        return PlayResult(
            ok=False,
            message=f"You don't see {target!r} here.",
            turn=save.turn,
            parsed_action="take",
            requires_agent=True,
        )
    if not item["portable"]:
        return PlayResult(
            ok=False,
            message=f"You can't take the {item['name']}.",
            turn=save.turn,
            parsed_action="take",
            parsed_action_id=item["id"],
        )

    conn.execute(
        """
        UPDATE items SET location_room_id = NULL, holder = 'player'
        WHERE world_id = ? AND id = ?
        """,
        (save.world_id, item["id"]),
    )
    save.inventory.append(item["id"])
    save.snapshot.inventory = list(save.inventory)

    change = {
        "op": "move_item",
        "item_id": item["id"],
        "from": save.current_room_id,
        "to": "inventory",
    }
    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="state_change",
        payload=change,
    )
    conn.commit()

    return PlayResult(
        ok=True,
        message=f"You take the {item['name']}.",
        turn=save.turn,
        parsed_action="take",
        parsed_action_id=item["id"],
        state_changes=[change],
    )


def _handle_drop(
    conn: sqlite3.Connection,
    save: SaveState,
    target: str,
) -> PlayResult:
    inv_items = [
        get_item_by_id(conn, save.world_id, item_id) for item_id in save.inventory
    ]
    inv_items = [i for i in inv_items if i]
    item = find_item_match(target, inv_items)
    if not item:
        return PlayResult(
            ok=False,
            message=f"You aren't carrying {target!r}.",
            turn=save.turn,
            parsed_action="drop",
            requires_agent=True,
        )

    save.inventory.remove(item["id"])
    save.snapshot.inventory = list(save.inventory)
    conn.execute(
        """
        UPDATE items SET location_room_id = ?, holder = NULL
        WHERE world_id = ? AND id = ?
        """,
        (save.current_room_id, save.world_id, item["id"]),
    )

    change = {
        "op": "move_item",
        "item_id": item["id"],
        "from": "inventory",
        "to": save.current_room_id,
    }
    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="state_change",
        payload=change,
    )
    conn.commit()

    return PlayResult(
        ok=True,
        message=f"You drop the {item['name']}.",
        turn=save.turn,
        parsed_action="drop",
        parsed_action_id=item["id"],
        state_changes=[change],
    )


def _handle_movement(
    conn: sqlite3.Connection,
    save: SaveState,
    action: dict[str, Any],
) -> PlayResult:
    ok, failed = evaluate_requirements(
        action["requires"],
        flags=save.flags,
        inventory=save.inventory,
    )
    if not ok:
        return PlayResult(
            ok=False,
            message=f"You can't do that yet (requires {failed}).",
            turn=save.turn,
            parsed_action="movement",
            parsed_action_id=action["id"],
        )

    if action["status"] == "blank" or action["target"] is None:
        payload = {
            "source_room": save.current_room_id,
            "action_id": action["id"],
            "generator_hint": action.get("generator_hint"),
        }
        log_event(
            conn,
            world_id=save.world_id,
            save_id=save.id,
            turn=save.turn,
            event_type="blank_exit_triggered",
            payload=payload,
        )
        return PlayResult(
            ok=False,
            message=(
                "You attempt to go that way, but the destination has not been "
                "committed to the world yet."
            ),
            turn=save.turn,
            parsed_action="movement",
            parsed_action_id=action["id"],
            blank_exit_triggered=payload,
            requires_agent=True,
            proposed_draft={
                "hint": action.get("generator_hint"),
                "source_room": save.current_room_id,
                "action_id": action["id"],
            },
        )

    target_room = _get_room(conn, save.world_id, action["target"])
    if not target_room:
        return PlayResult(
            ok=False,
            message="That exit leads nowhere yet.",
            turn=save.turn,
            parsed_action="movement",
            parsed_action_id=action["id"],
            requires_agent=True,
        )

    changes = apply_effects(action["effects"], flags=save.flags)
    from_room = save.current_room_id
    save.current_room_id = action["target"]
    save.snapshot.location = action["target"]
    if action["target"] not in save.snapshot.visited_rooms:
        save.snapshot.visited_rooms.append(action["target"])
    if action["target"] not in save.snapshot.known_rooms:
        save.snapshot.known_rooms.append(action["target"])

    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="state_change",
        payload={
            "op": "move_player",
            "from": from_room,
            "to": action["target"],
            "action_id": action["id"],
            "effects": changes,
        },
    )

    state_change: dict[str, Any] = {"op": "move_player", "to": action["target"]}
    if changes:
        state_change["effects"] = changes

    return PlayResult(
        ok=True,
        message=target_room["description"],
        turn=save.turn,
        parsed_action="movement",
        parsed_action_id=action["id"],
        state_changes=[state_change],
    )


def _handle_interaction(
    conn: sqlite3.Connection,
    save: SaveState,
    action: dict[str, Any],
) -> PlayResult:
    ok, failed = evaluate_requirements(
        action["requires"],
        flags=save.flags,
        inventory=save.inventory,
    )
    if not ok:
        return PlayResult(
            ok=False,
            message=f"You can't do that yet (requires {failed}).",
            turn=save.turn,
            parsed_action="interaction",
            parsed_action_id=action["id"],
        )

    changes = apply_effects(action["effects"], flags=save.flags)
    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="state_change",
        payload={
            "op": "interaction",
            "action_id": action["id"],
            "effects": changes,
        },
    )

    return PlayResult(
        ok=True,
        message=action["label"].capitalize() + ".",
        turn=save.turn,
        parsed_action="interaction",
        parsed_action_id=action["id"],
        state_changes=changes or [{"op": "interaction", "action_id": action["id"]}],
    )


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
    }
