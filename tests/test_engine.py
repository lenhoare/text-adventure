from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.actions import play
from engine.context import build_agent_context
from engine.db import connect, init_db
from engine.requires import RequiresError, evaluate_requirements
from engine.save_load import save_game
from engine.session import create_session, get_active_session, load_session
from engine.world_io import export_world, find_start_room, import_world, load_world_seed

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SEED_PATH = EXAMPLES / "world_seed.json"


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


def test_find_start_room():
    seed = load_world_seed(SEED_PATH)
    assert find_start_room(seed) == "hall"


def test_requires_dsl():
    flags = {"heard_house_settle": False}
    inventory = ["brass_key"]
    ok, _ = evaluate_requirements(
        ["inventory.brass_key", "!flags.heard_house_settle"],
        flags=flags,
        inventory=inventory,
    )
    assert ok

    ok, failed = evaluate_requirements(
        ["!flags.heard_house_settle"],
        flags={"heard_house_settle": True},
        inventory=[],
    )
    assert not ok
    assert failed == "!flags.heard_house_settle"

    with pytest.raises(RequiresError):
        evaluate_requirements(["bad.expr"], flags={}, inventory=[])


def test_movement_and_inventory(conn, world):
    save = get_active_session(conn, world)
    assert save is not None
    assert save.current_room_id == "hall"

    result = play(conn, save, "take brass key")
    assert result.ok
    assert "brass_key" in get_active_session(conn, world).inventory

    result = play(conn, get_active_session(conn, world), "go north")
    assert result.ok
    assert get_active_session(conn, world).current_room_id == "kitchen"


def test_blank_exit_requires_agent(conn, world):
    save = get_active_session(conn, world)
    result = play(conn, save, "go west")
    assert not result.ok
    assert result.requires_agent
    assert result.blank_exit_triggered is not None
    assert result.proposed_draft is not None


def test_interaction_sets_flag(conn, world):
    save = get_active_session(conn, world)
    result = play(conn, save, "listen to the house")
    assert result.ok
    save = get_active_session(conn, world)
    assert save.flags.get("heard_house_settle") is True


def test_save_and_load(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "take brass key")
    save = save_game(conn, world, "testsave")

    play(conn, get_active_session(conn, world), "go north")
    assert get_active_session(conn, world).current_room_id == "kitchen"

    loaded = load_session(conn, world, "testsave")
    assert loaded.current_room_id == "hall"
    assert "brass_key" in loaded.inventory


def test_export_world(conn, world):
    data = export_world(conn, world)
    assert data["world"]["id"] == "house_by_sea"
    assert "hall" in data["rooms"]
    assert "kitchen" in data["rooms"]["hall"]["items"] or "brass_key" in data["items"]


def test_agent_context(conn, world):
    context = build_agent_context(conn, world)
    assert context.current_room["id"] == "hall"
    assert any(a["kind"] == "movement" for a in context.visible_exits)

    context_with_input = build_agent_context(
        conn, world, player_input="go north"
    )
    assert context_with_input.candidate_actions
