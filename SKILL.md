---
name: text-adventure
description: text adventure / interactive fiction engine 
version: 0.2.0
author:  Len Hoare
license: MIT
platforms: [macos, linux]          # Optional — restrict to specific OS platforms
                                   #   Valid: macos, linux, windows
                                   #   Omit to load on all platforms (default)
metadata:
  hermes:
    tags: [games, adventure, text adventure]

---

# Text Adventure Engine Agent Skill

## Purpose

This repository contains a SQLite-backed text adventure / interactive fiction engine designed for use by AI agents and humans.

The core rule is:

> The engine remembers. The agent imagines.

The SQLite engine owns canonical state: worlds, sessions, saves, location, inventory, flags, events, random rolls, drafts, and committed world changes. Agents may narrate, interpret, suggest, and author new content, but they must use the `ta` command-line interface to inspect or modify game state.

Do not treat conversation memory as canonical game state.

---

## Environment setup

From the project root: home/len/dev/text-adventure

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## First principle for agents

Before doing anything else, run:

```bash
ta doctor --json
```

Do **not** run `ta init-db`, `ta import`, or `ta --world <id> new-session` until `ta doctor --json` has told you what already exists.

The default database lives at:

```text
~/.text_adventure/engine.db
```

This database persists across agent chats and shell sessions. A new agent conversation does **not** imply a fresh game database.

---

After setup, the `ta` command should be available inside the activated virtual environment.

Check:

```bash
ta --help
ta doctor --json
```

If `ta` is not found, activate the virtual environment again:

```bash
source .venv/bin/activate
```

There are also standalone entry points such as `ta-doctor`, `ta-play`, `ta-save`, `ta-load`, `ta-export`, `ta-import`, `ta-context`, `ta-draft`, `ta-apply-patch`, and `ta-roll`. Prefer the main `ta` command unless a standalone wrapper is explicitly more convenient.

---

## Agent startup workflow

Always start with:

```bash
ta doctor --json
```

Then follow this logic:

1. If `ok` is false, report the health-check problem and do not guess.
2. If `ready_to_play` is true, use the world id and active session reported by `doctor`.
3. If `ready_to_play` is false, follow the `hints` from the JSON output in order.
4. Re-run `ta doctor --json` after setup steps until it reports ready or gives a clear error.

Typical first-time setup, only if `doctor` says these steps are needed:

```bash
ta init-db
ta import examples/world_seed.json
ta --world house_by_sea new-session
ta doctor --json
```

Once ready:

```bash
ta --world house_by_sea context
ta --world house_by_sea play "look"
```

---

## Core concepts

### World

A world is the committed adventure setting: rooms, items, NPCs, exits, metadata, decks, tables, and rules.

Many worlds can live in one database. Select a world with:

```bash
ta --world <world_id> ...
```

### Session

A session is one active playthrough of a world. It tracks the current location, inventory, flags, known rooms, NPC state, random seed/draw count, turn number, and event history.

There is one active session per world.

### Save

A save is a named snapshot of the current session. Saves are for player progress. World export is different: export dumps the committed world layout, not the player’s current progress.

### Draft

A draft is proposed new content that is not yet canonical. Use drafts for LLM-created rooms, generated areas, revised descriptions, or content promoted from narration.

A draft can be shown, revised, committed, or rejected.

### Patch

A patch is a direct structured world mutation, such as adding a room, adding an exit, adding an item, **adding an NPC**, setting a flag, or batch-adding a hidden region. Patches are validated by the engine.

### Hidden region

A hidden room exists canonically but is filtered from normal player context until revealed, discovered, or entered.

### Event log

The event log is append-only. It records actions, state changes, randomness, discoveries, commits, and other significant events.

### Randomness

Randomness is engine-owned. Agents must never invent dice, coin, deck, or table results. Use the `roll` commands.

---

## Non-negotiable rules for agents

1. The SQLite engine is the source of truth.
2. Do not edit the database directly.
3. Do not manually edit canonical state files unless the user explicitly asks for file-level surgery.
4. Do not infer current location, inventory, flags, known rooms, or available exits from memory.
5. Use `ta --world <id> context` whenever state is uncertain.
6. Use `ta --world <id> play "<input>"` for player actions.
7. Prefer `--json` when making decisions from command output.
8. Treat CLI output as canonical even if it contradicts narration.
9. The agent may narrate possibilities, but possibilities are not real until committed by the engine.
10. Do not commit drafts unless the user asks, a test explicitly requires it, or the workflow is clearly marked as auto-commit.
11. Do not reveal hidden content to the player unless using author mode intentionally.
12. Do not invent random results. Use `ta roll ...`.
13. Prefer small, inspectable changes over large opaque changes.
14. If a command fails, read the error, run the relevant help command, and report honestly.

---

## Main command reference

### Health check

```bash
ta doctor
ta doctor --json
ta-doctor
```

Use this before setup or play.

`ta doctor --json` also flags **misplaced NPCs**: items with `metadata.npc`, `properties.npc`, or dialogue `metadata.topics` but no matching row in the `npcs` table. Follow the hint to apply `add_npc` (see `examples/npc_patch_example.json`).

```bash
ta init-db
```

Creates or upgrades the SQLite database. Only run after `ta doctor --json` indicates it is needed.

### Import a world

```bash
ta import examples/world_seed.json
```

Imports a world seed into the database.

### Export a world

```bash
ta --world <id> export
ta --world <id> export -o exports/world.json
```

Exports the committed world layout, not player progress.

### Start a session

```bash
ta --world <id> new-session
```

Starts a new active session for the world.

### Show session state

```bash
ta --world <id> session
```

Shows active session state.

### List saves

```bash
ta --world <id> list-saves
```

### Save current session

```bash
ta --world <id> save <name>
ta --world <id> save <name> --overwrite
```

### Load a named save

```bash
ta --world <id> load <name>
```

Loads the named save as the active session.

### Play a command

```bash
ta --world <id> play "look"
ta --world <id> play "take brass key"
ta --world <id> play "go north"
ta --world <id> play "ask cat about pantry"
ta --world <id> play "use brass key on locked cabinet"
```

For structured output:

```bash
ta --world <id> play "go west" --json
```

### Show current room

```bash
ta --world <id> show-room
ta --world <id> show-room --json
```

### Show known map

```bash
ta --world <id> show-map
```

### Agent context

```bash
ta --world <id> context
ta --world <id> context --input
ta --world <id> context --author
```

Use normal `context` for spoiler-safe player view.

Use `--input` when you need candidate actions or input-oriented help.

Use `--author` only when acting as a GM/author and when hidden information is allowed.

### Event log

```bash
ta --world <id> events
ta --world <id> events -o exports/events.jsonl
```

Exports events as JSONL.

---

## Playing commands

The engine matches player input against room actions, labels, aliases, and built-in verbs.

Common inputs:

```bash
ta --world <id> play "look"
ta --world <id> play "inventory"
ta --world <id> play "i"
ta --world <id> play "examine mirror"
ta --world <id> play "x mirror"
ta --world <id> play "take brass key"
ta --world <id> play "get brass key"
ta --world <id> play "drop brass key"
ta --world <id> play "go north"
ta --world <id> play "listen to the house"
ta --world <id> play "use key on cabinet"
ta --world <id> play "use key with cabinet"
ta --world <id> play "talk to cat"
ta --world <id> play "ask cat about pantry"
```

The `requires` DSL can refer to conditions such as:

```text
flags.some_flag
inventory.some_item
!flags.some_flag
!inventory.some_item
```

---

## Using context correctly

Use:

```bash
ta --world <id> context
```

The context bundle is the safest basis for narration and decision-making. It may include current room, visible exits, visible items, visible NPCs, inventory, flags, known rooms, recent events, available actions, and active drafts.

Player context is spoiler-safe. Hidden content is filtered.

Use:

```bash
ta --world <id> context --author
```

only when the user has explicitly asked for authoring, debugging, generation, hidden-region work, or GM-level inspection.

---

## Interpreting `play --json`

Prefer JSON output when an agent must decide what to do next:

```bash
ta --world <id> play "go west" --json
```

Important fields may include:

- `parsed_action` / `parsed_action_id` — what the engine understood
- `requires_agent` — the agent should narrate or interpret further
- `state_changes` — mechanical updates applied
- `blank_exit_triggered` — a blank exit was reached
- `proposed_draft` — the engine may have proposed draft scaffolding
- `candidate_actions` — possible matches when input could not be resolved
- `npc_talk` — NPC brief, topic, and canon facts for dialogue
- `roll_request` — reserved hook for agent-initiated rolls

If `requires_agent` is true, narrate using only the canonical facts returned by the engine/context. Do not invent lasting state unless you also create a draft or patch.

---

## Draft workflow

Drafts are for proposed content that should not become canonical until validated and committed.

### Add a draft

```bash
ta --world <id> draft add <file>
```

### Attach last narration as source text

```bash
ta --world <id> draft from-narration <file>
```

### List drafts

```bash
ta --world <id> draft list
ta --world <id> draft list --all-statuses
```

### Show a draft

```bash
ta --world <id> draft show <draft_id>
```

### Revise a draft

```bash
ta --world <id> draft revise <draft_id> <file>
```

### Commit a draft

```bash
ta --world <id> draft commit <draft_id>
```

### Reject a draft

```bash
ta --world <id> draft reject <draft_id>
```

### Agent rules for drafts

1. Use drafts for LLM-generated rooms, exits, descriptions, NPCs, and candidate content.
2. Do not commit a draft merely because it exists.
3. Show or summarize the draft to the user before committing, unless the user requested auto-generation and commit.
4. If attaching a new room to an existing room, include a return exit unless explicitly one-way.
5. When a blank exit triggered the draft, preserve the entry route and merge aliases where appropriate.
6. Use `draft revise` rather than creating multiple near-duplicate drafts.
7. Reject bad drafts instead of leaving clutter if the workflow makes rejection clear.

---

## Blank-exit workflow

A blank exit is an intentional route whose destination has not yet been committed.

Example:

```bash
ta --world house_by_sea play "go west" --json
```

If the result includes `blank_exit_triggered` or `proposed_draft`:

1. Treat the blank exit as a request for generation, not as a completed move.
2. Use the returned canonical facts and hints.
3. Create a draft room JSON file.
4. Add it with `ta --world <id> draft add <file>`.
5. Show/list the draft.
6. Commit only when asked or when the test explicitly requires it.
7. After commit, retry the movement command.

Example flow:

```bash
ta --world house_by_sea play "go west" --json
# write a draft JSON file, e.g. /tmp/cold_gallery.json
ta --world house_by_sea draft add /tmp/cold_gallery.json
ta --world house_by_sea draft list
ta --world house_by_sea draft show draft_cold_gallery_001
ta --world house_by_sea draft commit draft_cold_gallery_001
ta --world house_by_sea play "go west"
```

---

## Patch workflow

Patches are direct validated mutations.

Apply a patch:

```bash
ta --world <id> apply-patch <file>
```

Example:

```bash
ta --world house_by_sea apply-patch examples/commit_patch_example.json
ta --world house_by_sea apply-patch examples/hidden_region_patch.json
ta --world house_by_sea apply-patch examples/npc_patch_example.json
```

Known patch operations include:

- `add_room`
- `add_exit`
- `update_exit`
- `add_item`
- **`add_npc`**
- `move_item`
- `set_flag` / `clear_flag`
- `batch_add_region`

Agent rules for patches:

1. Prefer drafts for creative content.
2. Prefer patches for mechanical or deliberate world mutations.
3. Keep patch files small and inspectable.
4. Use hidden-region patterns for generated content that should exist but not yet be spoiled.
5. After applying a patch, run `context`, `show-room`, or `show-map` to verify the result.
6. **Use `add_npc` for characters — never `add_item` with `"npc": true`.**

---

## Hidden region workflow

Hidden rooms exist in the committed world but are filtered from normal player context.

Useful mechanisms:

- `discover_rooms` in effects makes a room name appear on the map as known before visiting.
- `reveal_exits` in effects makes a hidden exit visible for this save.
- Movement into a hidden room marks it known and visited and logs `room_discovered`.
- Hidden exits with `requires` can appear automatically once requirements are met.

For generated regions:

1. Use `batch_add_region`.
2. Set `default_room_status` to `hidden`.
3. Keep entry exits hidden.
4. Mark internal region exits as `committed` so navigation works once inside.
5. Use author context only when validating or debugging hidden regions.

---

## Item and puzzle rules

### Examine

Use:

```bash
ta --world <id> play "examine <item>"
ta --world <id> play "x <item>"
```

Item examination may trigger `on_examine` effects.

### Take and drop

Use:

```bash
ta --world <id> play "take <item>"
ta --world <id> play "get <item>"
ta --world <id> play "drop <item>"
```

Only portable items should enter inventory.

### Use X on Y

Use:

```bash
ta --world <id> play "use <tool> on <target>"
```

Also supports `with` and `against`.

Resolution order:

1. Explicit `properties.use_on.<target_id>` on the tool.
2. Target `properties.accepts_use.<tool_id>`.
3. Key pattern: `key_for` plus target `locked` / `unlock_flag`.

The tool must be in inventory.

---

## NPC dialogue workflow

### NPCs are not items

The engine stores **characters** and **objects** separately:

| | Items | NPCs |
|---|---|---|
| Table | `items` | `npcs` |
| Context field | `visible_items` | `visible_npcs` |
| Patch op | `add_item` | **`add_npc`** |
| World seed key | `"items"` | `"npcs"` |
| Dialogue (`talk` / `ask`) | No | Yes |

**Common mistake:** patching a bartender with `add_item` and `"npc": true` in metadata. The character may appear in the room description via `visible_items`, but `talk to bartender` and `ask bartender about …` will fail because dialogue only queries the `npcs` table.

**Fix:** apply an `add_npc` patch (or re-import a seed with an `"npcs"` block). Remove or repurpose any mistaken item row if needed.

### Adding an NPC with `add_npc`

```bash
ta --world <id> apply-patch examples/npc_patch_example.json
```

Patch op shape:

```json
{
  "op": "add_npc",
  "npc_id": "augmented_bartender",
  "payload": {
    "name": "augmented bartender",
    "description": "Chrome joints and a tired smile.",
    "location": "hall",
    "status": "committed",
    "state": { "trust": 0 },
    "metadata": {
      "voice": "Dry, clipped.",
      "role": "Gatekeeper of rumours.",
      "wants": "Payment in stories.",
      "wont": "Name names without reason.",
      "topics": {
        "data_chip": {
          "requires": [],
          "facts": ["The chip was last seen near the loading dock."],
          "effects": {
            "set_flags": {},
            "set_state": { "trust": 1 }
          }
        }
      }
    }
  }
}
```

Required fields: `npc_id`, `payload.name`, `payload.description`.

Optional: `location` (room id), `status` (default `committed`), `state`, `metadata` (brief + `topics`).

Validation: `npc_id` must be unique; `location` must exist (including rooms added earlier in the same patch).

**After patching, verify:**

```bash
ta --world <id> context --json
ta --world <id> play "talk to bartender" --json
```

Check that:

- the NPC appears in `visible_npcs` (not only `visible_items`)
- `play --json` returns `requires_agent: true` and an `npc_talk.brief` for free talk
- topic talk returns `npc_talk.facts` when the topic matches

Reference seed: `examples/world_seed.json` (`possible_cat` under `"npcs"`).

### Free talk

```bash
ta --world <id> play "talk to <npc>"
```

Also: `speak to …`, `talk … about …` (unknown topic), `ask <npc> about <unknown>`.

The engine logs the attempt and returns a brief. The agent performs dialogue, but should not invent lasting facts unless they become drafts, patches, flags, or state changes.

On success, `play --json` includes:

- `requires_agent: true`
- `npc_talk.brief` — `voice`, `role`, `wants`, `wont`, current `state`
- `npc_talk.topic: null` for free talk

The engine message is mechanical (e.g. “You address the possible cat.”) — **not** the character’s spoken lines.

### Topic dialogue

```bash
ta --world <id> play "ask <npc> about <topic>"
```

Also: `talk to <npc> about <topic>`, `ask about <topic> from <npc>`.

Topics live in `metadata.topics.<key>`. Topic keys are matched flexibly (`data chip` → `data_chip`).

Topics may include:

- `requires` — flag/inventory gates (same DSL as exits)
- `facts` — canon lines the agent must respect when narrating
- `effects` — `set_flags`, `discover_rooms`, `reveal_exits`, etc.
- `set_state` inside `effects` — per-save NPC state overlay

When the engine returns canon facts, use them. Do not contradict them.

On success, `play --json` includes `npc_talk.facts` and any `state_changes` from topic effects.

### NPC troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `You don't see '…' here.` on talk/ask | NPC not in `npcs` table or wrong room | `add_npc` patch; check `location` |
| Character in `visible_items` only | Created with `add_item` | Replace with `add_npc` |
| `doesn't seem to follow that topic` | Topic key missing from metadata | Add topic under `metadata.topics` (author context) |
| `isn't willing to discuss that yet` | Topic `requires` not met | Satisfy flags/inventory first |
| Talk returns action label, no `npc_talk` | Input matched a room **interaction** action instead | Use `talk to …` / `--json`; avoid duplicate interaction labels |
| Free talk “does nothing” | Expected pre-written lines | Engine delegates to agent via `requires_agent`; narrate from `npc_talk.brief` |

---

## Randomness workflow

All randomness must go through the engine.

### Dice

```bash
ta --world <id> roll dice "1d6+2" --reason "Luck check"
ta --world <id> roll dice "2d10+3" --reason "Reaction roll"
```

### Coin

```bash
ta --world <id> roll coin --reason "Which way?"
```

### Deck

```bash
ta --world <id> roll deck tarot_minor
```

### Weighted table

```bash
ta --world <id> roll table weather
```

Decks and tables are defined in `world.metadata.decks` and `world.metadata.tables`.

Agent rules:

1. Never invent results.
2. Roll first, narrate after.
3. Include the result in narration only after the engine returns it.
4. Do not reroll unless the rules or user ask for a reroll.
5. Treat random events as logged canonical events.

---

## Save/load workflow

List saves:

```bash
ta --world <id> list-saves
```

Save:

```bash
ta --world <id> save <name>
```

Overwrite save:

```bash
ta --world <id> save <name> --overwrite
```

Load:

```bash
ta --world <id> load <name>
```

After loading, run:

```bash
ta --world <id> context
```

---

## Export and event inspection

Export committed world JSON:

```bash
ta --world <id> export -o exports/world.json
```

Export event log:

```bash
ta --world <id> events -o exports/events.jsonl
```

Remember: world export is not the same as player progress.

---

## Standard smoke test

Only run setup steps if `ta doctor --json` indicates they are needed.

```bash
ta doctor --json
ta init-db
ta import examples/world_seed.json
ta --world house_by_sea new-session
ta --world house_by_sea play "look"
ta --world house_by_sea play "take brass key"
ta --world house_by_sea play "go north"
ta --world house_by_sea context
```

Expected broad behaviour:

- database initializes successfully
- world imports successfully
- new session is created
- `look` describes the starting room
- `take brass key` updates inventory or reports why it cannot
- `go north` changes location if a north exit exists
- `context` reflects canonical state

---

## Authoring workflow from user description

When the user describes a new room or location:

1. Ask only if the attachment point or intention is genuinely ambiguous.
2. Otherwise infer the likely attachment point from current context.
3. Create a draft JSON file.
4. Include room id, name, description, status, exits, items, and metadata as appropriate.
5. Include a return exit unless the user specifies one-way travel.
6. Add the draft with `ta --world <id> draft add <file>`.
7. Show the draft or summarize it.
8. Commit only after approval unless the user explicitly said to commit.

---

## Authoring workflow from narration

If the agent has just narrated a compelling provisional room and the user says something like:

- "commit that"
- "make that real"
- "save this room"
- "add this location"

then:

1. Convert the recent narration into structured draft content.
2. Preserve the tone but make the data concise.
3. Attach it to the current room or the relevant blank exit.
4. Add the draft.
5. Commit if the user explicitly asked to commit.
6. Run `context` or `show-room` to verify.

---

## What not to do

Do not do this:

```text
The player is probably still in the kitchen, so I will narrate the pantry.
```

Instead:

```bash
ta --world <id> context
```

Do not do this:

```text
The die roll is probably a 4 because that is dramatically good.
```

Instead:

```bash
ta --world <id> roll dice "1d6" --reason "Luck check"
```

Do not do this:

```text
I will add the cellar to the story in prose and assume it now exists.
```

Instead, create a draft or patch and commit it through the engine.

---

## Failure handling

If a command fails:

1. Preserve the exact command and error.
2. Run `ta --help` or the subcommand help if needed.
3. Run `ta doctor --json` if the environment or database may be the problem.
4. Run `ta --world <id> context` if game state may be the problem.
5. Do not guess hidden state.
6. Report what failed and what you tried.

Useful diagnostics:

```bash
ta --help
ta doctor --json
ta --world <id> context
ta --world <id> session
ta --world <id> draft list --all-statuses
```

---

## Testing

Run the project test suite with:

```bash
pytest
```

For agents, do not run destructive tests against a user’s real persistent database unless the test instructions explicitly say to do so. Prefer a temporary database with `--db` if available and appropriate.

---

## Summary for agents

1. Activate the venv.
2. Run `ta doctor --json`.
3. Follow `doctor` hints if not ready.
4. Use `context` before making stateful decisions.
5. Use `play` for player actions.
6. Use drafts or patches for world changes.
7. Use engine rolls for randomness.
8. Commit only when appropriate.
9. Never treat narration as canonical state.
10. The engine remembers; the agent imagines.
