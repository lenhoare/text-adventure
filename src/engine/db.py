from __future__ import annotations

import json
import sqlite3
from importlib import resources
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def default_db_path() -> Path:
    return Path.home() / ".text_adventure" / "engine.db"


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    schema = resources.files("engine").joinpath("schema.sql").read_text()
    conn.executescript(schema)
    current_version = conn.execute("PRAGMA user_version").fetchone()[0]
    if current_version < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)
