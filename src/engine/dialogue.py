from __future__ import annotations

import re
import sqlite3
from typing import Any

from engine.discovery import apply_gameplay_effects
from engine.events import log_event
from engine.models import PlayResult, SaveState
from engine.npcs import find_npc_match, get_npcs_in_room
from engine.requires import evaluate_requirements

TALK_PREFIXES = ("talk to ", "talk ", "speak to ", "speak ")
ABOUT_IN_PHRASE = re.compile(r"^(.+?)\s+about\s+(.+)$", re.IGNORECASE)
ASK_NPC_ABOUT = re.compile(r"^ask\s+(.+?)\s+about\s+(.+)$", re.IGNORECASE)
ASK_ABOUT_TO = re.compile(
    r"^ask\s+about\s+(.+?)\s+(?:to|from)\s+(.+)$", re.IGNORECASE
)


def parse_talk_command(text: str) -> tuple[str, str | None] | None:
    stripped = text.strip()
    if not stripped:
        return None

    match = ASK_NPC_ABOUT.match(stripped)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    match = ASK_ABOUT_TO.match(stripped)
    if match:
        return match.group(2).strip(), match.group(1).strip()

    lowered = stripped.lower()
    for prefix in TALK_PREFIXES:
        if lowered.startswith(prefix):
            rest = stripped[len(prefix) :].strip()
            about = ABOUT_IN_PHRASE.match(rest)
            if about:
                return about.group(1).strip(), about.group(2).strip()
            return rest, None

    return None


def normalize_topic_key(topic: str) -> str:
    return topic.strip().lower().replace(" ", "_")


def _resolve_topic(
    metadata: dict[str, Any], topic_text: str
) -> tuple[str, dict[str, Any]] | None:
    topics = metadata.get("topics", {})
    if not isinstance(topics, dict):
        return None

    normalized = normalize_topic_key(topic_text)
    if topic_text in topics:
        return topic_text, topics[topic_text]
    if normalized in topics:
        return normalized, topics[normalized]

    for key, value in topics.items():
        if normalize_topic_key(key) == normalized:
            return key, value
    return None


def _build_npc_brief(npc: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    brief: dict[str, Any] = {
        "id": npc["id"],
        "name": npc["name"],
        "description": npc["description"],
        "state": npc.get("state", {}),
    }
    for key in ("voice", "role", "wants", "wont"):
        if key in metadata:
            brief[key] = metadata[key]
    return brief


def apply_dialogue_effects(
    conn: sqlite3.Connection,
    save: SaveState,
    npc_id: str,
    effects: dict[str, Any],
    *,
    default_source_room: str | None = None,
) -> list[dict[str, Any]]:
    changes = apply_gameplay_effects(
        conn,
        save,
        effects,
        default_source_room=default_source_room,
    )

    set_state = effects.get("set_state")
    if isinstance(set_state, dict):
        overlay = dict(save.snapshot.npc_state.get(npc_id, {}))
        overlay.update(set_state)
        save.snapshot.npc_state[npc_id] = overlay
        changes.append(
            {
                "op": "set_npc_state",
                "npc_id": npc_id,
                "state": set_state,
            }
        )

    return changes


def _refresh_npc_brief(
    conn: sqlite3.Connection,
    save: SaveState,
    npc_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    npcs = get_npcs_in_room(
        conn, save.world_id, save.current_room_id, save=save, perspective="author"
    )
    for npc in npcs:
        if npc["id"] == npc_id:
            return _build_npc_brief(npc, metadata)
    return {"id": npc_id, "state": save.snapshot.npc_state.get(npc_id, {})}


def handle_talk(
    conn: sqlite3.Connection,
    save: SaveState,
    npc_text: str,
    topic_text: str | None,
) -> PlayResult:
    npcs = get_npcs_in_room(
        conn, save.world_id, save.current_room_id, save=save, perspective="author"
    )
    npc = find_npc_match(npc_text, npcs)
    if not npc:
        return PlayResult(
            ok=False,
            message=f"You don't see {npc_text!r} here.",
            turn=save.turn,
            parsed_action="talk",
            requires_agent=True,
        )

    metadata = npc.get("metadata", {})
    brief = _build_npc_brief(npc, metadata)
    parsed_action_id = npc["id"]

    if topic_text is None:
        log_event(
            conn,
            world_id=save.world_id,
            save_id=save.id,
            turn=save.turn,
            event_type="npc_talk",
            payload={
                "npc_id": npc["id"],
                "topic": None,
                "kind": "free_talk",
            },
        )
        conn.commit()
        return PlayResult(
            ok=True,
            message=f"You address the {npc['name']}.",
            turn=save.turn,
            parsed_action="talk",
            parsed_action_id=parsed_action_id,
            requires_agent=True,
            npc_talk={
                "npc_id": npc["id"],
                "topic": None,
                "facts": [],
                "brief": brief,
            },
        )

    resolved = _resolve_topic(metadata, topic_text)
    if not resolved:
        return PlayResult(
            ok=False,
            message=f"The {npc['name']} doesn't seem to follow that topic.",
            turn=save.turn,
            parsed_action="talk",
            parsed_action_id=parsed_action_id,
            requires_agent=True,
            npc_talk={
                "npc_id": npc["id"],
                "topic": topic_text,
                "facts": [],
                "brief": brief,
            },
        )

    topic_key, topic_rule = resolved
    requirements = list(topic_rule.get("requires", []))
    ok, failed = evaluate_requirements(
        requirements,
        flags=save.flags,
        inventory=save.inventory,
    )
    if not ok:
        return PlayResult(
            ok=False,
            message=f"The {npc['name']} isn't willing to discuss that yet (requires {failed}).",
            turn=save.turn,
            parsed_action="talk",
            parsed_action_id=parsed_action_id,
        )

    facts = list(topic_rule.get("facts", []))
    effects = topic_rule.get("effects", {})
    changes = apply_dialogue_effects(
        conn,
        save,
        npc["id"],
        effects if isinstance(effects, dict) else {},
        default_source_room=save.current_room_id,
    )

    log_event(
        conn,
        world_id=save.world_id,
        save_id=save.id,
        turn=save.turn,
        event_type="npc_talk",
        payload={
            "npc_id": npc["id"],
            "topic": topic_key,
            "kind": "topic",
            "facts": facts,
            "effects": changes,
        },
    )
    conn.commit()

    return PlayResult(
        ok=True,
        message=f"You ask the {npc['name']} about {topic_text}.",
        turn=save.turn,
        parsed_action="talk",
        parsed_action_id=f"{npc['id']}:{topic_key}",
        requires_agent=True,
        state_changes=changes,
        npc_talk={
            "npc_id": npc["id"],
            "topic": topic_key,
            "facts": facts,
            "brief": _refresh_npc_brief(conn, save, npc["id"], metadata),
        },
    )
