# Adventures — how this works

This project is a **text adventure engine** that remembers the truth of the game world. You (and an AI agent like Hermes) play and build stories together. The engine keeps track of where you are, what you carry, what exists, and what the player knows. The agent handles natural language — describing scenes, interpreting fuzzy commands, and proposing new places — but it does not get to change the world on its own.

**The engine remembers. The agent imagines.**

---

## The big idea

A text adventure is a **graph of places** connected by exits, filled with items, characters, and rules. The engine stores that graph durably and applies changes only when they pass validation.

When you type something like *go north* or *examine the brass key*, the engine tries to match your words to known actions. When that works, it updates state and returns a result. When it does not — ambiguous input, a blank exit, a moment that needs colour — it signals that the agent should step in and narrate or interpret.

World-building works the same way in reverse: the agent proposes structured changes (drafts or patches). The engine checks them and commits only what is valid.

---

## Worlds, sessions, and saves

**A world** is a complete adventure setting: rooms, items, exits, flags, and so on. You can keep **many worlds in one database**. Each world has an id (for example `house_by_sea`). You choose which world you are working on when you run commands.

**A session** is one playthrough of a world — where you are standing, what you are carrying, which flags are set, which rooms you have heard of or visited. There is **one active session per world** at a time.

**A save** is a named snapshot of a session you can return to later. Saving copies your current progress under a name; loading restores it. Playing on after a save does not overwrite that snapshot unless you save again with the same name.

**Export** dumps the committed world layout (the map as designed). It is not the same as a save — export is the authored world; save is where the player left off.

---

## Playing

Basic play is movement, looking, examining, taking, and dropping.

- **Look** — room description, visible exits, visible items.
- **Go** — follow an exit if the engine recognises the command and any requirements are met.
- **Examine / take / drop** — interact with items by name.

The engine matches your input against **action labels and aliases** defined in the world (for example `north`, `go north`, `kitchen`). It is not a full natural-language parser; the agent helps when input is vague.

Every turn is logged. The event log is an append-only history of inputs, state changes, discoveries, and world commits — useful for agents and for picking up where you left off.

---

## What the agent does while you play

The agent reads a **context bundle**: current room, visible exits and items, inventory, flags, recent events, known rooms, and available actions. In **player mode** this is filtered so hidden content does not leak.

The agent then:

- narrates results in prose
- parses ambiguous commands into something the engine can run
- suggests what might be possible next

When the engine returns `requires_agent`, that is the cue that human-facing narration or interpretation is needed before or after the mechanical result.

---

## Authoring while you play

You do not have to design the whole world upfront. Three patterns cover most cases.

### 1. Blank exits — invent on demand

A room can have an exit whose destination **does not exist yet** (a “blank” exit). The player tries it; the engine records that the blank was triggered; the agent describes what might be there. If everyone likes it, the agent turns that into a **draft**, you revise if needed, and **commit** it into the real world. The blank exit is wired up to the new room.

Good for: improvising one room at a time during play.

### 2. Drafts — propose, revise, commit

A **draft** is a structured proposal sitting outside the live world. It might describe a new room, its exits, and its items. Drafts can be edited repeatedly. **Commit** validates and merges them into the world. **Reject** discards them.

Good for: “make that corridor real” after narration, or refining a space before it becomes canonical.

### 3. Patches — direct world changes

A **patch** is a list of validated operations: add a room, add an exit, add an item, set a flag, add a whole region at once, and so on. Agents often produce patch JSON; the engine applies it in one go if everything checks out.

Good for: bulk authoring or precise edits the agent has already structured.

---

## Hidden regions — secrets baked into the world

Sometimes you want places that **already exist** in the world but the player has not found yet — a cellar under the kitchen, a wing behind a wall, five rooms beneath the house. That is different from a blank exit: the rooms are real in the database from the start; the player just does not know about them.

**Hidden rooms** do not appear in player context or on the map until discovery rules fire.

Discovery happens in three ways:

1. **Reach it** — walk in through a (possibly hidden) exit. Entering marks the room known and visited. That is the main loop.
2. **Clues** — examine something or perform an interaction whose effects include *discover room*. The player learns the **real name** on the map as “known but not visited” — a nudge toward finding it, not a spoiler-free vague label.
3. **Flags and hidden exits** — an exit stays hidden until a flag is set or an interaction *reveals* it (for example opening a trapdoor). Requirements on exits can also gate access (*needs the brass key*, *pantry not unlocked yet*).

When authoring a hidden region, commit the rooms as hidden, keep the **entry** from the known world hidden until revealed, and leave **internal** exits within the region normal so movement works once you are inside.

Use **author context** when the agent is building or running the world and must see hidden layout without spoiling the player. Use **player context** when narrating what the character actually perceives.

---

## Flags, keys, and conditions

Many puzzles are expressed as **flags** (has the player heard the house settle? is the trapdoor open?) and **inventory checks** (carrying the brass key). Exits and interactions can require these before they work.

Effects can set flags, discover rooms, reveal exits, or move items. The engine applies effects; the agent describes what it felt like.

---

## Randomness

Dice, coin flips, deck draws, and weighted tables are rolled by the **engine**, not the agent. Each result is logged with a seed and turn number so outcomes are fair and replayable. The agent asks for a roll; the engine returns the number; the agent narrates the consequence.

---

## Randomness, saves, and fairness

Because the engine owns location, inventory, flags, discovery, and rolls, agents cannot accidentally “remember wrong.” They read context, propose JSON when the world must change, and narrate around what the engine confirms.

Saves let you checkpoint progress. The event log lets you see how you got there. Export lets you share or backup the world design itself.

---

## A typical session arc

1. **Import** a seed world (or build one with patches).
2. **Start a session** — you begin in the starting area.
3. **Play** — look, move, take items; agent narrates; engine updates state.
4. Hit a **blank exit** — agent describes; draft and commit a new room.
5. Or apply a **hidden region** patch upfront — player discovers it through clues and exploration.
6. **Save** before a risky branch; **load** to retry.
7. **Export** the world when the layout is worth keeping as a template.

---

## Where to look for detail

- **This file** — concepts and workflows in plain language.
- **README** — setup, commands, and technical quick reference.
- **project_spec.md** — full design spec for contributors and agents.
- **examples/** — sample world seed, drafts, patches, and hidden region.

---

## Design motto

**The LLM can dream. The engine remembers.**

Use the agent for voice, creativity, and interpretation. Use the engine for what is true, what is fair, and what persists.
