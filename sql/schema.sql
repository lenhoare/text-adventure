PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'committed', 'hidden', 'discovered', 'deprecated')),
    description TEXT NOT NULL,
    coords_json TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (world_id, id),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    portable INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'committed',
    location_room_id TEXT,
    holder TEXT,
    properties_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (world_id, id),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, location_room_id) REFERENCES rooms(world_id, id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS npcs (
    id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    location_room_id TEXT,
    status TEXT NOT NULL DEFAULT 'committed',
    state_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (world_id, id),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, location_room_id) REFERENCES rooms(world_id, id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT NOT NULL,
    world_id TEXT NOT NULL,
    source_room_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('movement', 'interaction')),
    label TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    target_room_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('committed', 'hidden', 'blocked', 'blank', 'deprecated')),
    requires_json TEXT NOT NULL DEFAULT '[]',
    effects_json TEXT NOT NULL DEFAULT '{}',
    generator_hint TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (world_id, source_room_id, id),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, source_room_id) REFERENCES rooms(world_id, id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, target_room_id) REFERENCES rooms(world_id, id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    draft_type TEXT NOT NULL CHECK (draft_type IN ('room', 'item', 'npc', 'action', 'region', 'patch')),
    status TEXT NOT NULL CHECK (status IN ('active', 'committed', 'rejected', 'superseded')),
    source_turn INTEGER,
    source_event_id INTEGER,
    payload_json TEXT NOT NULL,
    notes TEXT,
    created_by TEXT NOT NULL CHECK (created_by IN ('user', 'llm', 'system')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS saves (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    name TEXT NOT NULL,
    current_room_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    inventory_json TEXT NOT NULL DEFAULT '[]',
    flags_json TEXT NOT NULL DEFAULT '{}',
    stats_json TEXT NOT NULL DEFAULT '{}',
    rng_json TEXT NOT NULL DEFAULT '{}',
    snapshot_json TEXT NOT NULL,
    last_event_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, current_room_id) REFERENCES rooms(world_id, id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id TEXT NOT NULL,
    save_id TEXT,
    turn INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS random_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id TEXT NOT NULL,
    turn INTEGER NOT NULL,
    random_type TEXT NOT NULL CHECK (random_type IN ('dice', 'coin', 'deck', 'table')),
    expression TEXT NOT NULL,
    result_json TEXT NOT NULL,
    reason TEXT,
    rng_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id TEXT NOT NULL,
    save_id TEXT,
    turn INTEGER NOT NULL,
    speaker TEXT NOT NULL CHECK (speaker IN ('player', 'engine', 'llm', 'system')),
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rooms_world_status ON rooms(world_id, status);
CREATE INDEX IF NOT EXISTS idx_actions_source ON actions(world_id, source_room_id);
CREATE INDEX IF NOT EXISTS idx_drafts_world_status ON drafts(world_id, status);
CREATE INDEX IF NOT EXISTS idx_events_world_turn ON events(world_id, turn);
CREATE INDEX IF NOT EXISTS idx_transcripts_world_turn ON transcripts(world_id, turn);
