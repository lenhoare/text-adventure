from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from engine.db import json_dumps, json_loads
from engine.events import log_event, new_id
from engine.patches import PatchValidationError, apply_ops, draft_payload_to_ops
from engine.session import get_active_session, persist_session


class DraftError(Exception):
    pass


def create_draft_from_payload(
    conn: sqlite3.Connection,
    world_id: str,
    payload: dict[str, Any],
    *,
    save_id: str | None = None,
    created_by: str = "llm",
) -> dict[str, Any]:
    draft_data = payload.get("draft", payload)
    draft_id = draft_data.get("id") or new_id("draft")
    draft_type = draft_data.get("draft_type", "room")
    source_turn = draft_data.get("source_turn")
    notes = draft_data.get("source_text") or draft_data.get("notes")

    conn.execute(
        """
        INSERT INTO drafts (
            id, world_id, draft_type, status, source_turn,
            payload_json, notes, created_by
        ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
        """,
        (
            draft_id,
            world_id,
            draft_type,
            source_turn,
            json_dumps(draft_data.get("payload", draft_data)),
            notes,
            created_by,
        ),
    )
    conn.commit()

    save = get_active_session(conn, world_id)
    turn = source_turn or (save.turn if save else 0)
    log_event(
        conn,
        world_id=world_id,
        save_id=save_id or (save.id if save else None),
        turn=turn,
        event_type="draft_created",
        payload={"draft_id": draft_id, "draft_type": draft_type},
    )
    return get_draft(conn, draft_id)


def create_draft_from_file(
    conn: sqlite3.Connection,
    world_id: str,
    path: Path | str,
    *,
    save_id: str | None = None,
) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    draft_data = data.get("draft", data)
    created_by = draft_data.get("created_by", "llm")
    return create_draft_from_payload(
        conn,
        world_id,
        draft_data,
        save_id=save_id,
        created_by=created_by,
    )


def create_draft_from_last_narration(
    conn: sqlite3.Connection,
    world_id: str,
    draft_path: Path | str,
    *,
    save_id: str | None = None,
) -> dict[str, Any]:
    save = get_active_session(conn, world_id)
    if not save:
        raise DraftError("No active session")

    row = conn.execute(
        """
        SELECT text FROM transcripts
        WHERE world_id = ? AND save_id = ? AND speaker = 'llm'
        ORDER BY id DESC
        LIMIT 1
        """,
        (world_id, save.id),
    ).fetchone()
    if not row:
        row = conn.execute(
            """
            SELECT payload_json FROM events
            WHERE world_id = ? AND save_id = ? AND event_type = 'llm_narration'
            ORDER BY id DESC
            LIMIT 1
            """,
            (world_id, save.id),
        ).fetchone()
        source_text = json_loads(row["payload_json"], {}).get("text") if row else None
    else:
        source_text = row["text"]

    if not source_text:
        raise DraftError("No prior LLM narration found in session")

    data = json.loads(Path(draft_path).read_text())
    draft_data = data.get("draft", data)
    draft_data["source_turn"] = draft_data.get("source_turn", save.turn)
    draft_data["source_text"] = source_text
    return create_draft_from_payload(
        conn,
        world_id,
        draft_data,
        save_id=save.id,
        created_by=draft_data.get("created_by", "llm"),
    )


def get_draft(conn: sqlite3.Connection, draft_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    if not row:
        raise DraftError(f"Draft {draft_id!r} not found")
    return _row_to_draft(row)


def list_drafts(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    status: str | None = "active",
) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            """
            SELECT * FROM drafts
            WHERE world_id = ? AND status = ?
            ORDER BY created_at DESC
            """,
            (world_id, status),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM drafts
            WHERE world_id = ?
            ORDER BY created_at DESC
            """,
            (world_id,),
        ).fetchall()
    return [_row_to_draft(row) for row in rows]


def revise_draft(
    conn: sqlite3.Connection,
    draft_id: str,
    revision_path: Path | str,
) -> dict[str, Any]:
    draft = get_draft(conn, draft_id)
    if draft["status"] != "active":
        raise DraftError(f"Draft {draft_id!r} is not active")

    data = json.loads(Path(revision_path).read_text())
    draft_data = data.get("draft", data)
    new_payload = draft_data.get("payload", draft_data)

    conn.execute(
        """
        UPDATE drafts SET
            payload_json = ?,
            notes = COALESCE(?, notes),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            json_dumps(new_payload),
            draft_data.get("source_text") or draft_data.get("notes"),
            draft_id,
        ),
    )
    conn.commit()
    return get_draft(conn, draft_id)


def reject_draft(
    conn: sqlite3.Connection,
    world_id: str,
    draft_id: str,
    *,
    save_id: str | None = None,
) -> dict[str, Any]:
    draft = get_draft(conn, draft_id)
    if draft["world_id"] != world_id:
        raise DraftError(f"Draft {draft_id!r} does not belong to world {world_id!r}")
    if draft["status"] != "active":
        raise DraftError(f"Draft {draft_id!r} is not active")

    conn.execute(
        """
        UPDATE drafts SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (draft_id,),
    )
    conn.commit()

    save = get_active_session(conn, world_id)
    log_event(
        conn,
        world_id=world_id,
        save_id=save_id or (save.id if save else None),
        turn=save.turn if save else 0,
        event_type="draft_rejected",
        payload={"draft_id": draft_id},
    )
    return get_draft(conn, draft_id)


def commit_draft(
    conn: sqlite3.Connection,
    world_id: str,
    draft_id: str,
    *,
    save_id: str | None = None,
    author: str = "llm",
    manage_revision: bool = True,
) -> dict[str, Any]:
    draft = get_draft(conn, draft_id)
    if draft["world_id"] != world_id:
        raise DraftError(f"Draft {draft_id!r} does not belong to world {world_id!r}")
    if draft["status"] != "active":
        raise DraftError(f"Draft {draft_id!r} is not active")

    save = get_active_session(conn, world_id)
    ops = draft_payload_to_ops(conn, world_id, draft["payload"])

    sid = save_id or (save.id if save else None)
    applied = apply_ops(conn, world_id, ops, save_id=sid)

    event_id = None
    if manage_revision:
        conn.execute(
            """
            UPDATE worlds SET version = version + 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (world_id,),
        )
        if save:
            save.snapshot.world_revision += 1
            persist_session(conn, save)

        event_id = log_event(
            conn,
            world_id=world_id,
            save_id=sid,
            turn=draft.get("source_turn") or (save.turn if save else 0),
            event_type="patch_committed",
            payload={
                "patch_id": f"patch_from_{draft_id}",
                "author": author,
                "ops": applied,
                "draft_id": draft_id,
            },
        )

    conn.execute(
        """
        UPDATE drafts SET status = 'committed', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (draft_id,),
    )
    conn.commit()

    return {
        "ok": True,
        "patch_id": f"patch_from_{draft_id}",
        "draft_id": draft_id,
        "ops_applied": applied,
        "event_id": event_id,
    }


def _row_to_draft(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "world_id": row["world_id"],
        "draft_type": row["draft_type"],
        "status": row["status"],
        "source_turn": row["source_turn"],
        "source_event_id": row["source_event_id"],
        "payload": json_loads(row["payload_json"], {}),
        "notes": row["notes"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
