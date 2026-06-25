from __future__ import annotations

import random
import re
import sqlite3
from typing import Any

from engine.db import json_dumps, json_loads
from engine.session import default_rng_state, get_active_session, persist_session

DICE_PATTERN = re.compile(
    r"^(?P<count>\d+)d(?P<sides>\d+)(?P<mod>[+-]\d+)?$",
    re.IGNORECASE,
)


class RngError(Exception):
    pass


def ensure_session_rng(conn: sqlite3.Connection, world_id: str) -> dict[str, Any]:
    save = get_active_session(conn, world_id)
    if not save:
        raise RngError(f"No active session for world {world_id!r}")
    if not save.rng:
        save.rng = default_rng_state()
        persist_session(conn, save)
    return save.rng


def _advance_rng(state: dict[str, Any]) -> random.Random:
    rng = random.Random(state["seed"])
    for _ in range(state["draw_count"]):
        rng.random()
    return rng


def _record_draw(
    conn: sqlite3.Connection,
    *,
    world_id: str,
    turn: int,
    random_type: str,
    expression: str,
    result: dict[str, Any],
    reason: str | None,
    rng_before: dict[str, Any],
    rng_after: dict[str, Any],
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO random_events (
            world_id, turn, random_type, expression, result_json, reason, rng_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            world_id,
            turn,
            random_type,
            expression,
            json_dumps(result),
            reason,
            json_dumps(
                {
                    "algorithm": rng_after.get("algorithm", "python_random"),
                    "seed": rng_after["seed"],
                    "draw_count_before": rng_before["draw_count"],
                    "draw_count_after": rng_after["draw_count"],
                }
            ),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def roll_dice(
    conn: sqlite3.Connection,
    world_id: str,
    expression: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    match = DICE_PATTERN.match(expression.replace(" ", ""))
    if not match:
        raise RngError(f"Invalid dice expression: {expression!r}")

    count = int(match.group("count"))
    sides = int(match.group("sides"))
    mod_text = match.group("mod")
    modifier = int(mod_text) if mod_text else 0

    save = get_active_session(conn, world_id)
    if not save:
        raise RngError(f"No active session for world {world_id!r}")

    rng_before = dict(save.rng or default_rng_state())
    if not save.rng:
        save.rng = rng_before

    roller = _advance_rng(save.rng)
    rolls = [roller.randint(1, sides) for _ in range(count)]
    total = sum(rolls) + modifier
    save.rng["draw_count"] += 1
    rng_after = dict(save.rng)
    persist_session(conn, save)

    result = {
        "rolls": rolls,
        "modifier": modifier,
        "total": total,
    }
    event_id = _record_draw(
        conn,
        world_id=world_id,
        turn=save.turn,
        random_type="dice",
        expression=expression,
        result=result,
        reason=reason,
        rng_before=rng_before,
        rng_after=rng_after,
    )
    return {
        "random_type": "dice",
        "expression": expression,
        "result": result,
        "reason": reason,
        "event_id": event_id,
        "rng": {
            "seed": rng_after["seed"],
            "draw_count_before": rng_before["draw_count"],
            "draw_count_after": rng_after["draw_count"],
        },
    }


def flip_coin(
    conn: sqlite3.Connection,
    world_id: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    save = get_active_session(conn, world_id)
    if not save:
        raise RngError(f"No active session for world {world_id!r}")

    rng_before = dict(save.rng or default_rng_state())
    if not save.rng:
        save.rng = rng_before

    roller = _advance_rng(save.rng)
    outcome = "heads" if roller.random() < 0.5 else "tails"
    save.rng["draw_count"] += 1
    rng_after = dict(save.rng)
    persist_session(conn, save)

    result = {"outcome": outcome}
    event_id = _record_draw(
        conn,
        world_id=world_id,
        turn=save.turn,
        random_type="coin",
        expression="flip",
        result=result,
        reason=reason,
        rng_before=rng_before,
        rng_after=rng_after,
    )
    return {
        "random_type": "coin",
        "expression": "flip",
        "result": result,
        "reason": reason,
        "event_id": event_id,
    }


def _world_metadata(conn: sqlite3.Connection, world_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT metadata_json FROM worlds WHERE id = ?", (world_id,)
    ).fetchone()
    if not row:
        raise RngError(f"World {world_id!r} not found")
    return json_loads(row["metadata_json"], {})


def draw_deck(
    conn: sqlite3.Connection,
    world_id: str,
    deck_name: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    metadata = _world_metadata(conn, world_id)
    decks = metadata.get("decks", {})
    cards = decks.get(deck_name)
    if not cards:
        raise RngError(f"Deck {deck_name!r} not found in world metadata")

    save = get_active_session(conn, world_id)
    if not save:
        raise RngError(f"No active session for world {world_id!r}")

    rng_before = dict(save.rng or default_rng_state())
    if not save.rng:
        save.rng = rng_before

    roller = _advance_rng(save.rng)
    card = cards[roller.randrange(len(cards))]
    save.rng["draw_count"] += 1
    rng_after = dict(save.rng)
    persist_session(conn, save)

    result = {"deck": deck_name, "card": card}
    event_id = _record_draw(
        conn,
        world_id=world_id,
        turn=save.turn,
        random_type="deck",
        expression=deck_name,
        result=result,
        reason=reason,
        rng_before=rng_before,
        rng_after=rng_after,
    )
    return {
        "random_type": "deck",
        "expression": deck_name,
        "result": result,
        "reason": reason,
        "event_id": event_id,
    }


def choose_table(
    conn: sqlite3.Connection,
    world_id: str,
    table_name: str,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    metadata = _world_metadata(conn, world_id)
    tables = metadata.get("tables", {})
    entries = tables.get(table_name)
    if not entries:
        raise RngError(f"Table {table_name!r} not found in world metadata")

    save = get_active_session(conn, world_id)
    if not save:
        raise RngError(f"No active session for world {world_id!r}")

    weights = [int(entry.get("weight", 1)) for entry in entries]
    total = sum(weights)
    if total <= 0:
        raise RngError(f"Table {table_name!r} has no positive weights")

    rng_before = dict(save.rng or default_rng_state())
    if not save.rng:
        save.rng = rng_before

    roller = _advance_rng(save.rng)
    pick = roller.randrange(total)
    cumulative = 0
    chosen = entries[-1]
    for entry, weight in zip(entries, weights):
        cumulative += weight
        if pick < cumulative:
            chosen = entry
            break

    save.rng["draw_count"] += 1
    rng_after = dict(save.rng)
    persist_session(conn, save)

    result = {"table": table_name, "choice": chosen.get("result", chosen)}
    event_id = _record_draw(
        conn,
        world_id=world_id,
        turn=save.turn,
        random_type="table",
        expression=table_name,
        result=result,
        reason=reason,
        rng_before=rng_before,
        rng_after=rng_after,
    )
    return {
        "random_type": "table",
        "expression": table_name,
        "result": result,
        "reason": reason,
        "event_id": event_id,
    }
