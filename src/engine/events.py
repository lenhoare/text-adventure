from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from engine.db import json_dumps, json_loads, row_to_dict


def log_event(
    conn: sqlite3.Connection,
    *,
    world_id: str,
    save_id: str | None,
    turn: int,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO events (world_id, save_id, turn, event_type, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (world_id, save_id, turn, event_type, json_dumps(payload)),
    )
    conn.commit()
    return int(cursor.lastrowid)


def log_transcript(
    conn: sqlite3.Connection,
    *,
    world_id: str,
    save_id: str | None,
    turn: int,
    speaker: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO transcripts (world_id, save_id, turn, speaker, text, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            world_id,
            save_id,
            turn,
            speaker,
            text,
            json_dumps(metadata or {}),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_recent_events(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    limit: int = 10,
    save_id: str | None = None,
) -> list[dict[str, Any]]:
    if save_id:
        rows = conn.execute(
            """
            SELECT id, turn, event_type, payload_json, created_at
            FROM events
            WHERE world_id = ? AND save_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (world_id, save_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, turn, event_type, payload_json, created_at
            FROM events
            WHERE world_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (world_id, limit),
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in reversed(rows):
        events.append(
            {
                "id": row["id"],
                "turn": row["turn"],
                "event_type": row["event_type"],
                "payload": json_loads(row["payload_json"], {}),
                "created_at": row["created_at"],
            }
        )
    return events


def export_events_jsonl(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    save_id: str | None = None,
) -> str:
    if save_id:
        rows = conn.execute(
            """
            SELECT turn, event_type, payload_json
            FROM events
            WHERE world_id = ? AND save_id = ?
            ORDER BY id ASC
            """,
            (world_id, save_id),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT turn, event_type, payload_json
            FROM events
            WHERE world_id = ?
            ORDER BY id ASC
            """,
            (world_id,),
        ).fetchall()

    lines: list[str] = []
    for row in rows:
        payload = json_loads(row["payload_json"], {})
        record = {
            "turn": row["turn"],
            "event_type": row["event_type"],
            "payload": payload,
        }
        lines.append(json.dumps(record, separators=(",", ":")))
    return "\n".join(lines) + ("\n" if lines else "")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
