"""Phase 2 tests: patches, drafts, and RNG."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.actions import play
from engine.db import connect, init_db
from engine.drafts import commit_draft, create_draft_from_file, list_drafts, reject_draft
from engine.patches import PatchValidationError, apply_patch
from engine.rng import flip_coin, roll_dice
from engine.session import create_session, get_active_session
from engine.world_io import export_world, import_world

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SEED_PATH = EXAMPLES / "world_seed.json"
DRAFT_PATH = EXAMPLES / "draft_room_from_narration.json"
PATCH_PATH = EXAMPLES / "commit_patch_example.json"


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    connection = connect(db_path)
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def world(conn):
    import_world(conn, SEED_PATH)
    create_session(conn, "house_by_sea", seed_path=str(SEED_PATH))
    return "house_by_sea"


def test_apply_commit_patch(conn, world):
    data = json.loads(PATCH_PATH.read_text())
    result = apply_patch(conn, data)
    assert result["ok"]
    assert "add_room" in result["ops_applied"]

    exported = export_world(conn, world)
    assert "cold_gallery" in exported["rooms"]
    assert "scraped_portraits" in exported["items"]


def test_commit_draft_updates_blank_exit(conn, world):
    draft = create_draft_from_file(conn, world, DRAFT_PATH)
    result = commit_draft(conn, world, draft["id"])
    assert result["ok"]

    row = conn.execute(
        """
        SELECT target_room_id, status FROM actions
        WHERE world_id = ? AND source_room_id = 'hall' AND id = 'through_velvet_curtain'
        """,
        (world,),
    ).fetchone()
    assert row["target_room_id"] == "cold_gallery"
    assert row["status"] == "committed"

    save = get_active_session(conn, world)
    result = play(conn, save, "go west")
    assert result.ok
    assert get_active_session(conn, world).current_room_id == "cold_gallery"


def test_reject_draft(conn, world):
    draft = create_draft_from_file(conn, world, DRAFT_PATH)
    rejected = reject_draft(conn, world, draft["id"])
    assert rejected["status"] == "rejected"
    assert list_drafts(conn, world, status="active") == []


def test_patch_validation_duplicate_room(conn, world):
    data = json.loads(PATCH_PATH.read_text())
    apply_patch(conn, data)
    with pytest.raises(PatchValidationError):
        apply_patch(conn, data)


def test_rng_is_deterministic_with_seed(conn, world):
    save = get_active_session(conn, world)
    save.rng = {"algorithm": "python_random", "seed": 12345, "draw_count": 0}
    from engine.session import persist_session

    persist_session(conn, save)

    first = roll_dice(conn, world, "1d6", reason="test")
    second = roll_dice(conn, world, "1d6", reason="test")

    save = get_active_session(conn, world)
    save.rng = {"algorithm": "python_random", "seed": 12345, "draw_count": 0}
    persist_session(conn, save)
    replay = roll_dice(conn, world, "1d6", reason="test")

    assert first["result"]["total"] == replay["result"]["total"]
    assert first["result"]["total"] != second["result"]["total"] or first == second

    coin = flip_coin(conn, world, reason="test")
    assert coin["result"]["outcome"] in {"heads", "tails"}
