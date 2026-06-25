from __future__ import annotations

import re
import sqlite3
from typing import Any

from engine.db import json_loads
from engine.discovery import apply_gameplay_effects
from engine.events import log_event
from engine.models import PlayResult, SaveState
from engine.requires import evaluate_requirements

USE_ON_PATTERNS = (
    re.compile(r"^use\s+(.+?)\s+on\s+(.+)$", re.IGNORECASE),
    re.compile(r"^use\s+(.+?)\s+with\s+(.+)$", re.IGNORECASE),
    re.compile(r"^use\s+(.+?)\s+against\s+(.+)$", re.IGNORECASE),
)


def parse_use_command(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    for pattern in USE_ON_PATTERNS:
        match = pattern.match(stripped)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None


def _inventory_items(
    conn: sqlite3.Connection, world_id: str, save: SaveState
) -> list[dict[str, Any]]:
    from engine.actions import get_item_by_id

    items: list[dict[str, Any]] = []
    for item_id in save.inventory:
        item = get_item_by_id(conn, world_id, item_id)
        if item:
            items.append(item)
    return items


def _find_target(
    conn: sqlite3.Connection,
    world_id: str,
    room_id: str,
    target_text: str,
) -> dict[str, Any] | None:
    from engine.actions import find_item_match, get_items_in_room
    from engine.npcs import find_npc_match, get_npcs_in_room

    room_items = get_items_in_room(conn, world_id, room_id)
    target = find_item_match(target_text, room_items)
    if target:
        target["kind"] = "item"
        return target

    npcs = get_npcs_in_room(conn, world_id, room_id)
    matched = find_npc_match(target_text, npcs)
    if matched:
        matched["kind"] = "npc"
    return matched


def _resolve_use_rule(
    tool: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any] | None:
    tool_props = tool.get("properties", {})
    target_props = target.get("properties", {})
    target_id = target["id"]

    explicit = tool_props.get("use_on", {})
    if isinstance(explicit, dict) and target_id in explicit:
        rule = dict(explicit[target_id])
        rule.setdefault(
            "message",
            f"You use the {tool['name']} on the {target['name']}.",
        )
        return rule

    accepts = target_props.get("accepts_use", {})
    if isinstance(accepts, dict) and tool["id"] in accepts:
        rule = dict(accepts[tool["id"]])
        rule.setdefault(
            "message",
            f"You use the {tool['name']} on the {target['name']}.",
        )
        return rule

    key_for = tool_props.get("key_for", [])
    if target_id in key_for and target_props.get("locked"):
        unlock_flag = target_props.get("unlock_flag")
        if unlock_flag:
            return {
                "requires": [f"!flags.{unlock_flag}"],
                "effects": {"set_flags": {unlock_flag: True}},
                "message": (
                    f"You use the {tool['name']} on the {target['name']}. "
                    "It unlocks."
                ),
            }

    return None


def handle_use_on(
    conn: sqlite3.Connection,
    save: SaveState,
    tool_text: str,
    target_text: str,
) -> PlayResult:
    from engine.actions import find_item_match

    tool = find_item_match(tool_text, _inventory_items(conn, save.world_id, save))
    if not tool:
        return PlayResult(
            ok=False,
            message=f"You aren't carrying {tool_text!r}.",
            turn=save.turn,
            parsed_action="use_on",
            requires_agent=True,
        )

    target = _find_target(conn, save.world_id, save.current_room_id, target_text)
    if not target:
        return PlayResult(
            ok=False,
            message=f"You don't see {target_text!r} here.",
            turn=save.turn,
            parsed_action="use_on",
            requires_agent=True,
        )

    rule = _resolve_use_rule(tool, target)
    if not rule:
        return PlayResult(
            ok=False,
            message=f"You can't use the {tool['name']} on the {target['name']}.",
            turn=save.turn,
            parsed_action="use_on",
            parsed_action_id=f"{tool['id']}:{target['id']}",
            requires_agent=True,
        )

    requirements = list(rule.get("requires", []))
    inventory_req = f"inventory.{tool['id']}"
    if inventory_req not in requirements:
        requirements.insert(0, inventory_req)

    ok, failed = evaluate_requirements(
        requirements,
        flags=save.flags,
        inventory=save.inventory,
    )
    if not ok:
        return PlayResult(
            ok=False,
            message=f"You can't do that yet (requires {failed}).",
            turn=save.turn,
            parsed_action="use_on",
            parsed_action_id=f"{tool['id']}:{target['id']}",
        )

    effects = rule.get("effects", {})
    changes = apply_gameplay_effects(
        conn,
        save,
        effects,
        default_source_room=save.current_room_id,
    )

    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="state_change",
        payload={
            "op": "use_on",
            "tool_id": tool["id"],
            "target_id": target["id"],
            "target_kind": target.get("kind", "item"),
            "effects": changes,
        },
    )
    conn.commit()

    return PlayResult(
        ok=True,
        message=str(rule.get("message", "Done.")),
        turn=save.turn,
        parsed_action="use_on",
        parsed_action_id=f"{tool['id']}:{target['id']}",
        state_changes=[
            {
                "op": "use_on",
                "tool_id": tool["id"],
                "target_id": target["id"],
                **({"effects": changes} if changes else {}),
            }
        ],
    )
