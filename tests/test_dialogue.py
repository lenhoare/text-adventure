"""Tests for NPC talk / dialogue hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.actions import play
from engine.dialogue import parse_talk_command
from engine.session import create_session, get_active_session
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


def test_parse_talk_command():
    assert parse_talk_command("talk to possible cat") == ("possible cat", None)
    assert parse_talk_command("talk cat about pantry") == ("cat", "pantry")
    assert parse_talk_command("ask possible cat about house") == (
        "possible cat",
        "house",
    )
    assert parse_talk_command("ask about pantry from cat") == ("cat", "pantry")


def _go_kitchen(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "go north")
    return get_active_session(conn, world)


def test_free_talk_requires_agent(conn, world):
    save = _go_kitchen(conn, world)
    result = play(conn, save, "talk to possible cat")
    assert result.ok
    assert result.requires_agent
    assert result.npc_talk is not None
    assert result.npc_talk["topic"] is None
    assert result.npc_talk["brief"]["voice"]


def test_topic_requires_flag(conn, world):
    save = _go_kitchen(conn, world)
    result = play(conn, save, "ask cat about pantry")
    assert not result.ok
    assert "isn't willing" in result.message


def test_topic_unlocked_grants_facts_and_state(conn, world):
    save = get_active_session(conn, world)
    play(conn, save, "take brass key")
    play(conn, get_active_session(conn, world), "go north")
    play(conn, get_active_session(conn, world), "use brass key on pantry")

    result = play(conn, get_active_session(conn, world), "ask cat about pantry")
    assert result.ok
    assert result.requires_agent
    assert result.npc_talk["facts"]
    save = get_active_session(conn, world)
    assert save.flags.get("cat_warned_pantry") is True
    assert save.snapshot.npc_state["possible_cat"]["trust"] == 1


def test_free_topic_always_available(conn, world):
    save = _go_kitchen(conn, world)
    result = play(conn, save, "talk to cat about house")
    assert result.ok
    assert result.npc_talk["topic"] == "house"
    save = get_active_session(conn, world)
    assert save.snapshot.npc_state["possible_cat"]["seen_clearly"] is True
