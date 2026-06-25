from __future__ import annotations

import json
from pathlib import Path

from engine.db import SCHEMA_VERSION, connect, init_db
from engine.doctor import EXAMPLE_WORLD_ID, run_doctor
from engine.session import create_session
from engine.world_io import import_world

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SEED_PATH = EXAMPLES / "world_seed.json"


def test_doctor_reports_ready_state(tmp_path, monkeypatch):
    db_path = tmp_path / "engine.db"
    monkeypatch.chdir(tmp_path)

    report = run_doctor(db_path)
    assert report["package"]["ok"] is True
    assert report["database"]["exists"] is False
    assert report["ok"] is True
    assert report["ready_to_play"] is False
    assert any("init-db" in hint for hint in report["hints"])

    conn = connect(db_path)
    init_db(conn)
    import_world(conn, SEED_PATH)
    create_session(conn, EXAMPLE_WORLD_ID, seed_path=str(SEED_PATH))
    conn.close()

    report = run_doctor(db_path)
    assert report["database"]["exists"] is True
    assert report["database"]["schema_version"]["actual"] == SCHEMA_VERSION
    assert report["database"]["schema_version"]["ok"] is True
    assert report["database"]["example_world_loaded"] is True
    assert report["database"]["session_count"] == 1
    assert report["ready_to_play"] is True
    assert report["example_seed"]["ok"] is True


def test_doctor_json_roundtrip(tmp_path, monkeypatch):
    db_path = tmp_path / "engine.db"
    monkeypatch.chdir(tmp_path)
    report = run_doctor(db_path)
    payload = json.loads(json.dumps(report, default=str))
    assert payload["database"]["path"] == str(db_path)
