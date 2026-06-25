"""Tests for use X on Y puzzle rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.actions import play
from engine.patches import apply_patch
from engine.session import create_session, get_active_session
from engine.use_on import parse_use_command
from engine.world_io import import_world

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SEED_PATH = EXAMPLES / "world_seed.json"


@pytest.fixture
def conn(tmp_path):
    from engine.db import connect, init_db

    connection = connect(tmp_path / "test.db")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def world(conn):
    import_world(conn, SEED_PATH)
    create_session(conn, "house_by_sea", seed_path=str(SEED_PATH))
    return "house_by_sea"


def test_parse_use_command():
    assert parse_use_command("use brass key on pantry") == ("brass key", "pantry")
    assert parse_use_command("use rope with hook") == ("rope", "hook")
    assert parse_use_command("USE OIL against hinge") == ("OIL", "hinge")
    assert parse_use_command("use key") is None


def test_key_for_unlocks_target(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "take brass key")
    play(conn, get_active_session(conn, world), "go north")
    save = get_active_session(conn, world)

    result = play(conn, save, "use brass key on locked pantry")
    assert result.ok
    assert result.parsed_action == "use_on"
    assert get_active_session(conn, world).flags.get("pantry_unlocked") is True


def test_use_on_without_tool_fails(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    result = play(conn, get_active_session(conn, world), "use brass key on pantry")
    assert not result.ok
    assert "aren't carrying" in result.message


def test_use_on_no_rule_requires_agent(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "take brass key")
    play(conn, get_active_session(conn, world), "go north")
    save = get_active_session(conn, world)

    result = play(conn, save, "use brass key on green apple")
    assert not result.ok
    assert result.requires_agent


def test_explicit_use_on_rule(conn, world):
    apply_patch(
        conn,
        {
            "patch": {
                "id": "patch_oil_hinge",
                "world_id": "house_by_sea",
                "ops": [
                    {
                        "op": "add_item",
                        "item_id": "oil_can",
                        "payload": {
                            "name": "small oil can",
                            "description": "A dented can of machine oil.",
                            "portable": True,
                            "location": "kitchen",
                            "properties": {
                                "use_on": {
                                    "locked_pantry": {
                                        "requires": ["flags.pantry_unlocked"],
                                        "effects": {
                                            "set_flags": {"pantry_oiled": True}
                                        },
                                        "message": "You oil the pantry hinges. They stop squeaking.",
                                    }
                                },
                            },
                        },
                    }
                ],
            }
        },
    )

    save = get_active_session(conn, world)
    play(conn, save, "take brass key")
    play(conn, get_active_session(conn, world), "go north")
    save = get_active_session(conn, world)
    play(conn, save, "use brass key on pantry")
    play(conn, get_active_session(conn, world), "take oil can")
    save = get_active_session(conn, world)

    result = play(conn, save, "use oil can on locked pantry")
    assert result.ok
    assert get_active_session(conn, world).flags.get("pantry_oiled") is True
