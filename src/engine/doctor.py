from __future__ import annotations

import os
import sqlite3
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

from engine.db import SCHEMA_VERSION, default_db_path, json_loads

EXAMPLE_WORLD_ID = "house_by_sea"
EXAMPLE_SEED_NAME = "world_seed.json"

REQUIRED_TABLES = (
    "worlds",
    "rooms",
    "items",
    "npcs",
    "actions",
    "drafts",
    "saves",
    "active_sessions",
    "events",
    "random_events",
    "transcripts",
)


def _example_seed_paths() -> list[Path]:
    candidates = [
        Path.cwd() / "examples" / EXAMPLE_SEED_NAME,
        Path(__file__).resolve().parents[2] / "examples" / EXAMPLE_SEED_NAME,
    ]
    seen: set[Path] = set()
    paths: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            paths.append(resolved)
    return paths


def _find_example_seed() -> Path | None:
    for path in _example_seed_paths():
        if path.is_file():
            return path
    return None


def _check_venv() -> dict[str, Any]:
    virtual_env = os.environ.get("VIRTUAL_ENV")
    in_venv = sys.prefix != sys.base_prefix
    active = bool(virtual_env or in_venv)
    return {
        "ok": active,
        "active": active,
        "virtual_env": virtual_env,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
    }


def _check_package() -> dict[str, Any]:
    try:
        import engine

        distribution = None
        try:
            distribution = metadata.version("text-adventure-engine")
        except metadata.PackageNotFoundError:
            pass

        return {
            "ok": True,
            "name": "text-adventure-engine",
            "version": engine.__version__,
            "distribution_version": distribution,
            "module_path": str(Path(engine.__file__).resolve()),
        }
    except ImportError as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def _list_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {row[0] for row in rows}


def _item_looks_like_npc(properties: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if properties.get("npc") is True:
        return True
    if metadata.get("npc") is True:
        return True
    topics = metadata.get("topics")
    return isinstance(topics, dict) and bool(topics)


def _find_misplaced_npc_items(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT world_id, id, name, location_room_id, properties_json, metadata_json
        FROM items
        ORDER BY world_id, id
        """
    ).fetchall()
    misplaced: list[dict[str, Any]] = []
    for row in rows:
        properties = json_loads(row["properties_json"], {})
        metadata = json_loads(row["metadata_json"], {})
        if not _item_looks_like_npc(properties, metadata):
            continue
        npc_row = conn.execute(
            "SELECT 1 FROM npcs WHERE world_id = ? AND id = ?",
            (row["world_id"], row["id"]),
        ).fetchone()
        if npc_row:
            continue
        reasons: list[str] = []
        if properties.get("npc") is True:
            reasons.append("properties.npc is true")
        if metadata.get("npc") is True:
            reasons.append("metadata.npc is true")
        if isinstance(metadata.get("topics"), dict) and metadata["topics"]:
            reasons.append("metadata.topics present")
        misplaced.append(
            {
                "world_id": row["world_id"],
                "item_id": row["id"],
                "name": row["name"],
                "location": row["location_room_id"],
                "reasons": reasons,
            }
        )
    return misplaced


def _check_database(db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "path": str(db_path),
        "exists": db_path.is_file(),
    }
    if not db_path.is_file():
        result["hint"] = "Run `ta init-db` to create the database."
        return result

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        actual_version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = _list_tables(conn)
        missing_tables = sorted(set(REQUIRED_TABLES) - tables)
        schema_ok = actual_version == SCHEMA_VERSION and not missing_tables

        worlds = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, title, version, created_at, updated_at
                FROM worlds
                ORDER BY id
                """
            ).fetchall()
        ]
        sessions = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    a.world_id,
                    s.id AS save_id,
                    s.name AS save_name,
                    s.turn,
                    s.current_room_id
                FROM active_sessions a
                JOIN saves s ON s.id = a.save_id
                ORDER BY a.world_id
                """
            ).fetchall()
        ]
        example_world_loaded = any(world["id"] == EXAMPLE_WORLD_ID for world in worlds)
        misplaced_npc_items = _find_misplaced_npc_items(conn)

        result.update(
            {
                "ok": schema_ok,
                "schema_version": {
                    "ok": schema_ok,
                    "expected": SCHEMA_VERSION,
                    "actual": actual_version,
                    "missing_tables": missing_tables,
                },
                "worlds": worlds,
                "world_count": len(worlds),
                "sessions": sessions,
                "session_count": len(sessions),
                "example_world_loaded": example_world_loaded,
                "misplaced_npc_items": misplaced_npc_items,
                "misplaced_npc_items_ok": not misplaced_npc_items,
            }
        )
        if actual_version != SCHEMA_VERSION:
            result["hint"] = "Run `ta init-db` to upgrade the database schema."
        elif missing_tables:
            result["hint"] = "Run `ta init-db` to create missing tables."
        return result
    except sqlite3.Error as exc:
        result["error"] = str(exc)
        result["hint"] = "Check database path permissions or run `ta init-db`."
        return result
    finally:
        conn.close()


def _check_example_seed() -> dict[str, Any]:
    seed_path = _find_example_seed()
    searched = [str(path) for path in _example_seed_paths()]
    if seed_path is None:
        return {
            "ok": False,
            "world_id": EXAMPLE_WORLD_ID,
            "searched_paths": searched,
            "hint": f"Expected `{EXAMPLE_SEED_NAME}` under an examples/ directory.",
        }
    return {
        "ok": True,
        "world_id": EXAMPLE_WORLD_ID,
        "path": str(seed_path),
        "searched_paths": searched,
    }


def run_doctor(db_path: Path | None = None) -> dict[str, Any]:
    """Collect environment and database diagnostics for agents."""
    resolved_db = db_path or default_db_path()
    venv = _check_venv()
    package = _check_package()
    example_seed = _check_example_seed()
    database = _check_database(resolved_db)

    ready_to_play = (
        package["ok"]
        and database["exists"]
        and database.get("schema_version", {}).get("ok", False)
        and database.get("example_world_loaded", False)
        and database.get("session_count", 0) > 0
    )

    ok = package["ok"] and (
        not database["exists"] or database.get("schema_version", {}).get("ok", False)
    )

    hints: list[str] = []
    if not venv["ok"]:
        hints.append("Activate the project virtualenv before running ta commands.")
    if not package["ok"]:
        hints.append("Install the package, e.g. `pip install -e .`.")
    if not database["exists"]:
        hints.append("Run `ta init-db`.")
    elif not database.get("schema_version", {}).get("ok", False) and database.get("hint"):
        hints.append(database["hint"])
    if example_seed["ok"] and database["exists"] and not database.get("example_world_loaded"):
        hints.append(f"Run `ta import {example_seed['path']}`.")
    if database.get("example_world_loaded") and database.get("session_count", 0) == 0:
        hints.append(f"Run `ta --world {EXAMPLE_WORLD_ID} new-session`.")
    for entry in database.get("misplaced_npc_items", []):
        hints.append(
            "Character "
            f"{entry['item_id']!r} in world {entry['world_id']!r} is an item with "
            f"{', '.join(entry['reasons'])} but no matching npcs row — use `add_npc` "
            "instead of `add_item` (see examples/npc_patch_example.json)."
        )

    return {
        "ok": ok,
        "ready_to_play": ready_to_play,
        "venv": venv,
        "package": package,
        "database": database,
        "example_seed": example_seed,
        "hints": hints,
    }


def render_doctor_report(report: dict[str, Any]) -> str:
    lines = [
        f"overall: {'ok' if report['ok'] else 'issues'}",
        f"ready_to_play: {'yes' if report['ready_to_play'] else 'no'}",
    ]

    venv = report["venv"]
    lines.append(
        "venv: "
        + ("ok" if venv["ok"] else "inactive")
        + (f" ({venv['virtual_env']})" if venv.get("virtual_env") else "")
    )

    package = report["package"]
    if package["ok"]:
        lines.append(f"package: ok ({package['name']} {package['version']})")
    else:
        lines.append(f"package: failed ({package.get('error', 'unknown error')})")

    database = report["database"]
    if not database["exists"]:
        lines.append(f"database: missing ({database['path']})")
    else:
        schema = database["schema_version"]
        schema_status = "ok" if schema["ok"] else "mismatch"
        lines.append(
            f"database: {schema_status} ({database['path']}, schema v{schema['actual']})"
        )
        if schema["missing_tables"]:
            lines.append(f"  missing tables: {', '.join(schema['missing_tables'])}")

    example_seed = report["example_seed"]
    if example_seed["ok"]:
        lines.append(f"example seed: ok ({example_seed['path']})")
    else:
        lines.append("example seed: not found")

    if database.get("exists"):
        worlds = database.get("worlds", [])
        if worlds:
            world_ids = ", ".join(world["id"] for world in worlds)
            lines.append(f"worlds ({len(worlds)}): {world_ids}")
        else:
            lines.append("worlds: none")

        if database.get("example_world_loaded") is False and example_seed["ok"]:
            lines.append(f"example world in db: missing ({EXAMPLE_WORLD_ID})")

        sessions = database.get("sessions", [])
        if sessions:
            lines.append("sessions:")
            for session in sessions:
                lines.append(
                    "  "
                    f"{session['world_id']}: {session['save_name']} "
                    f"(turn {session['turn']}, room {session['current_room_id']})"
                )
        else:
            lines.append("sessions: none active")

        misplaced = database.get("misplaced_npc_items", [])
        if misplaced:
            lines.append(f"npc-as-item issues ({len(misplaced)}):")
            for entry in misplaced:
                lines.append(
                    "  "
                    f"{entry['world_id']}/{entry['item_id']} ({entry['name']!r}): "
                    f"{', '.join(entry['reasons'])}"
                )
        elif database.get("misplaced_npc_items_ok"):
            lines.append("npc-as-item: ok")

    for hint in report.get("hints", []):
        lines.append(f"hint: {hint}")

    return "\n".join(lines)
