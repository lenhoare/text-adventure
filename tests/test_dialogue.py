"""Tests for NPC talk / dialogue hooks."""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.actions import play
from engine.context import build_agent_context
from engine.dialogue import parse_talk_command
from engine.patches import PatchValidationError, apply_patch
from engine.session import create_session, get_active_session
from engine.world_io import export_world, import_world

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


def test_add_npc_patch_enables_dialogue(conn, world):
    result = apply_patch(
        conn,
        {
            "patch": {
                "id": "patch_bartender_001",
                "world_id": world,
                "ops": [
                    {
                        "op": "add_npc",
                        "npc_id": "augmented_bartender",
                        "payload": {
                            "name": "augmented bartender",
                            "description": "Chrome joints and a tired smile.",
                            "location": "hall",
                            "metadata": {
                                "voice": "Dry, clipped, loyal to the house tab.",
                                "role": "Gatekeeper of rumours.",
                                "topics": {
                                    "data_chip": {
                                        "facts": [
                                            "The chip was last seen near the loading dock."
                                        ]
                                    }
                                },
                            },
                        },
                    }
                ],
            }
        },
    )
    assert result["ok"]
    assert "add_npc" in result["ops_applied"]

    exported = export_world(conn, world)
    assert "augmented_bartender" in exported["npcs"]

    save = get_active_session(conn, world)
    context = build_agent_context(conn, world)
    assert any(npc["id"] == "augmented_bartender" for npc in context.visible_npcs)

    talk = play(conn, save, "talk to bartender")
    assert talk.ok
    assert talk.requires_agent
    assert talk.npc_talk["brief"]["voice"]

    topic = play(conn, get_active_session(conn, world), "ask bartender about data chip")
    assert topic.ok
    assert topic.npc_talk["facts"] == [
        "The chip was last seen near the loading dock."
    ]


def test_add_npc_rejects_missing_room(conn, world):
    with pytest.raises(PatchValidationError) as exc:
        apply_patch(
            conn,
            {
                "patch": {
                    "id": "patch_bad_npc",
                    "world_id": world,
                    "ops": [
                        {
                            "op": "add_npc",
                            "npc_id": "ghost",
                            "payload": {
                                "name": "ghost",
                                "description": "Nowhere.",
                                "location": "missing_room",
                            },
                        }
                    ],
                }
            },
        )
    assert "missing_room" in str(exc.value)


def test_add_npc_allows_room_added_in_same_patch(conn, world):
    apply_patch(
        conn,
        {
            "patch": {
                "id": "patch_room_and_npc",
                "world_id": world,
                "ops": [
                    {
                        "op": "add_room",
                        "room_id": "back_alley",
                        "payload": {
                            "name": "Back Alley",
                            "region": "city",
                            "status": "committed",
                            "description": "Rain-slick bricks.",
                        },
                    },
                    {
                        "op": "add_npc",
                        "npc_id": "fixer",
                        "payload": {
                            "name": "fixer",
                            "description": "Watches from the shadows.",
                            "location": "back_alley",
                        },
                    },
                ],
            }
        },
    )
    exported = export_world(conn, world)
    assert exported["npcs"]["fixer"]["location"] == "back_alley"
