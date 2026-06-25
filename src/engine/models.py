from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RoomStatus = Literal["proposed", "committed", "hidden", "discovered", "deprecated"]
ActionKind = Literal["movement", "interaction"]
ActionStatus = Literal["committed", "hidden", "blocked", "blank", "deprecated"]
Speaker = Literal["player", "engine", "llm", "system"]


class Coords(BaseModel):
    region: str
    x: int = 0
    y: int = 0
    z: int = 0


class WorldMeta(BaseModel):
    id: str
    title: str
    description: str | None = None
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoomSeed(BaseModel):
    id: str
    name: str
    region: str
    status: RoomStatus
    description: str
    coords: Coords | None = None
    tags: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    npcs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ItemSeed(BaseModel):
    id: str
    name: str
    description: str
    portable: bool = True
    status: str = "committed"
    location: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NpcSeed(BaseModel):
    id: str
    name: str
    description: str
    location: str | None = None
    status: str = "committed"
    state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionSeed(BaseModel):
    id: str
    kind: ActionKind
    label: str
    aliases: list[str] = Field(default_factory=list)
    target: str | None = None
    status: ActionStatus = "committed"
    requires: list[str] = Field(default_factory=list)
    effects: dict[str, Any] = Field(default_factory=dict)
    generator_hint: str | None = None
    return_action: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorldSeed(BaseModel):
    world: WorldMeta
    rooms: dict[str, RoomSeed]
    actions: dict[str, list[ActionSeed]] = Field(default_factory=dict)
    items: dict[str, ItemSeed] = Field(default_factory=dict)
    npcs: dict[str, NpcSeed] = Field(default_factory=dict)


class SessionSnapshot(BaseModel):
    location: str
    visited_rooms: list[str] = Field(default_factory=list)
    known_rooms: list[str] = Field(default_factory=list)
    revealed_exits: list[str] = Field(default_factory=list)
    inventory: list[str] = Field(default_factory=list)
    world_revision: int = 1


class SaveState(BaseModel):
    id: str
    world_id: str
    name: str
    current_room_id: str
    turn: int = 0
    inventory: list[str] = Field(default_factory=list)
    flags: dict[str, Any] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    rng: dict[str, Any] = Field(default_factory=dict)
    last_event_id: int | None = None
    snapshot: SessionSnapshot


class PlayResult(BaseModel):
    ok: bool
    message: str
    turn: int
    parsed_action: str | None = None
    parsed_action_id: str | None = None
    state_changes: list[dict[str, Any]] = Field(default_factory=list)
    blank_exit_triggered: dict[str, Any] | None = None
    proposed_draft: dict[str, Any] | None = None
    roll_request: dict[str, Any] | None = None
    candidate_actions: list[dict[str, Any]] = Field(default_factory=list)
    requires_agent: bool = False


class AgentContext(BaseModel):
    perspective: Literal["player", "author"] = "player"
    world_id: str
    save_id: str
    turn: int
    current_room: dict[str, Any]
    visible_exits: list[dict[str, Any]]
    visible_items: list[dict[str, Any]]
    visible_npcs: list[dict[str, Any]]
    inventory: list[dict[str, Any]]
    flags: dict[str, Any]
    stats: dict[str, Any]
    known_rooms: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]]
    available_actions: list[dict[str, Any]]
    candidate_actions: list[dict[str, Any]] = Field(default_factory=list)
    active_drafts: list[dict[str, Any]] = Field(default_factory=list)
    hidden_rooms: list[dict[str, Any]] = Field(default_factory=list)
    hidden_exits: list[dict[str, Any]] = Field(default_factory=list)
