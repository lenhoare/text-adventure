# LLM Text Adventure Engine

SQLite-backed interactive fiction engine for AI agents. The engine owns canonical state; agents (like Hermes) handle narration and propose structured changes.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick start

```bash
ta init-db
ta import examples/world_seed.json
ta --world house_by_sea new-session
ta --world house_by_sea play "look"
ta --world house_by_sea play "take brass key"
ta --world house_by_sea play "go north"
ta --world house_by_sea context
```

Default database path: `~/.text_adventure/engine.db` (override with `--db`).

## CLI commands

| Command | Description |
|---|---|
| `ta init-db` | Create or upgrade the SQLite database |
| `ta import <seed.json>` | Import a world seed |
| `ta export` | Export world JSON (`-o` to write a file) |
| `ta --world <id> new-session` | Start a new active session |
| `ta --world <id> session` | Show active session state |
| `ta --world <id> list-saves` | List named saves |
| `ta --world <id> save <name>` | Snapshot current session to a named save |
| `ta --world <id> load <name>` | Load a named save as the active session |
| `ta --world <id> play "<input>"` | Apply player input (`--json` for structured result) |
| `ta --world <id> show-room` | Show current room |
| `ta --world <id> show-map` | Show known rooms |
| `ta --world <id> context` | Emit agent context bundle (JSON) |
| `ta --world <id> events` | Export event log as JSONL |

Standalone script entry points are also available: `ta-play`, `ta-save`, `ta-load`, etc.

## Agent integration

Each `play` result includes structured fields for agent follow-up:

- `parsed_action` / `parsed_action_id` — what the engine understood
- `requires_agent` — true when the LLM should narrate or interpret further
- `blank_exit_triggered` / `proposed_draft` — blank exit hit, destination not yet committed
- `candidate_actions` — partial matches when input could not be resolved
- `roll_request` — reserved for Phase 2 RNG hooks

Use `ta context` (or `build_agent_context()` in Python) to fetch current room, visible exits/items/NPCs, inventory, flags, recent events, and available actions.

## Phase 1 scope

- SQLite schema with WAL and foreign keys
- World import/export JSON
- Room graph, movement, examine/take/drop
- Formal `requires` DSL (`flags.*`, `inventory.*`, with `!` negation)
- One active session per world
- Named save snapshots (load restores; play continues on active session)
- Append-only event log and transcripts

## Phase 2 scope

- **Drafts** — propose room/content JSON, revise, commit, or reject
- **Patches** — validated world mutations (`add_room`, `add_exit`, `update_exit`, `add_item`, flags, `batch_add_region`, etc.)
- **Blank exits** — committing a room draft updates the existing blank exit in-place (aliases merged)
- **RNG** — engine-owned dice, coin flips, deck draws, and weighted tables (logged to `random_events`)

### Draft workflow

```bash
ta --world house_by_sea play "go west" --json          # blank_exit_triggered
# Agent writes examples/draft_room_from_narration.json
ta --world house_by_sea draft add examples/draft_room_from_narration.json
ta --world house_by_sea draft show draft_cold_gallery_001
ta --world house_by_sea draft commit draft_cold_gallery_001
ta --world house_by_sea play "go west"
```

Or apply a patch file directly:

```bash
ta --world house_by_sea apply-patch examples/commit_patch_example.json
```

### Randomness

```bash
ta --world house_by_sea roll dice "1d6+2" --reason "Luck check"
ta --world house_by_sea roll coin --reason "Which way?"
```

Decks and tables are read from `world.metadata.decks` and `world.metadata.tables` in the seed JSON.

### New CLI commands

| Command | Description |
|---|---|
| `ta draft add <file>` | Create draft from JSON |
| `ta draft from-narration <file>` | Attach last LLM narration as source text |
| `ta draft list` | List active drafts |
| `ta draft show <id>` | Show draft |
| `ta draft revise <id> <file>` | Replace draft payload |
| `ta draft commit <id>` | Validate and commit draft to world |
| `ta draft reject <id>` | Reject draft |
| `ta apply-patch <file>` | Apply a patch JSON file |
| `ta roll dice <expr>` | Roll dice (e.g. `2d10+3`) |
| `ta roll coin` | Flip a coin |
| `ta roll deck <name>` | Draw from world metadata deck |
| `ta roll table <name>` | Choose from weighted table |

Agent context (`ta context`) now includes `active_drafts`.

See `project_spec.md` for the full design and Phase 3 roadmap.

## Files

- `project_spec.md` — design document
- `sql/schema.sql` — reference schema (canonical copy in `src/engine/schema.sql`)
- `examples/` — seed world, save, patch, and event examples

## Tests

```bash
pytest
```
