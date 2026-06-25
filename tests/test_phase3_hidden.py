"""Phase 3 tests: hidden regions and discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.actions import play
from engine.context import build_agent_context, render_map
from engine.db import connect, init_db
from engine.patches import apply_patch
from engine.session import create_session, get_active_session
from engine.world_io import import_world

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SEED_PATH = EXAMPLES / "world_seed.json"
HIDDEN_PATCH = EXAMPLES / "hidden_region_patch.json"


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
    apply_patch(conn, json.loads(HIDDEN_PATCH.read_text()))
    create_session(conn, "house_by_sea", seed_path=str(SEED_PATH))
    return "house_by_sea"


def test_hidden_rooms_not_on_player_map(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    save = get_active_session(conn, world)

    context = build_agent_context(conn, world, perspective="player")
    assert context.hidden_rooms == []
    assert "cellar_landing" not in {r["id"] for r in context.known_rooms}

    author = build_agent_context(conn, world, perspective="author")
    hidden_ids = {r["id"] for r in author.hidden_rooms}
    assert "cellar_landing" in hidden_ids
    assert "wine_vault" in hidden_ids


def test_clue_discover_room_by_name(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    save = get_active_session(conn, world)

    result = play(conn, save, "examine note scratched into floorboard")
    assert result.ok
    assert any(c.get("op") == "discover_room" for c in result.state_changes)

    context = build_agent_context(conn, world)
    known = {r["id"]: r for r in context.known_rooms}
    assert "cellar_landing" in known
    assert known["cellar_landing"]["name"] == "Cellar Landing"
    assert known["cellar_landing"]["visited"] is False

    map_text = render_map(conn, world)
    assert "Cellar Landing" in map_text
    assert "[known]" in map_text


def test_reveal_exit_and_enter_hidden_region(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    save = get_active_session(conn, world)

    play(conn, save, "open trapdoor")
    save = get_active_session(conn, world)
    assert save.flags.get("trapdoor_open") is True
    assert "kitchen:down_to_cellar" in save.snapshot.revealed_exits

    result = play(conn, save, "descend to the cellar")
    assert result.ok
    assert get_active_session(conn, world).current_room_id == "cellar_landing"

    context = build_agent_context(conn, world)
    known = {r["id"]: r for r in context.known_rooms}
    assert known["cellar_landing"]["visited"] is True

    result = play(conn, get_active_session(conn, world), "go east to the wine vault")
    assert result.ok
    assert get_active_session(conn, world).current_room_id == "wine_vault"


def test_hidden_exit_visible_when_requires_met(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    save = get_active_session(conn, world)

    play(conn, save, "open trapdoor")
    context = build_agent_context(conn, world)
    exit_ids = {e["id"] for e in context.visible_exits}
    assert "down_to_cellar" in exit_ids
