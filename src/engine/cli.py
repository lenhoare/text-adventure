from __future__ import annotations

import json
from pathlib import Path

import click

from engine.actions import play
from engine.context import build_agent_context, render_map
from engine.db import connect, default_db_path, init_db
from engine.drafts import (
    commit_draft,
    create_draft_from_file,
    create_draft_from_last_narration,
    get_draft,
    list_drafts,
    reject_draft,
    revise_draft,
)
from engine.events import export_events_jsonl
from engine.patches import PatchValidationError, apply_patch
from engine.rng import choose_table, draw_deck, flip_coin, roll_dice
from engine.save_load import save_game
from engine.session import create_session, get_active_session, list_saves, load_session
from engine.world_io import export_world, import_world


def _resolve_db(db: Path | None) -> Path:
    return db or default_db_path()


def _resolve_world(ctx: click.Context) -> str:
    world_id = ctx.obj.get("world_id")
    if not world_id:
        raise click.ClickException("Missing --world. Set it on the command or via `ta init`.")
    return world_id


def _output_json(data: object, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, indent=2, default=str))
    elif isinstance(data, dict) and "message" in data:
        click.echo(data["message"])
    elif hasattr(data, "model_dump"):
        click.echo(json.dumps(data.model_dump(), indent=2))


@click.group()
@click.option("--db", type=click.Path(path_type=Path), default=None, help="SQLite database path")
@click.option("--world", "world_id", default=None, help="Active world id")
@click.pass_context
def main(ctx: click.Context, db: Path | None, world_id: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["db"] = _resolve_db(db)
    ctx.obj["world_id"] = world_id


@main.command("init-db")
@click.pass_context
def init_db_cmd(ctx: click.Context) -> None:
    """Create or upgrade the SQLite database."""
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(f"Initialized database at {ctx.obj['db']}")


@main.command("import")
@click.argument("seed_path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def import_cmd(ctx: click.Context, seed_path: Path) -> None:
    """Import a world seed JSON file."""
    conn = connect(ctx.obj["db"])
    init_db(conn)
    world_id = import_world(conn, seed_path)
    click.echo(f"Imported world {world_id!r}")


@main.command("export")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.pass_context
def export_cmd(ctx: click.Context, output: Path | None) -> None:
    """Export a world to JSON."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    data = export_world(conn, world_id)
    text = json.dumps(data, indent=2)
    if output:
        output.write_text(text)
        click.echo(f"Exported world {world_id!r} to {output}")
    else:
        click.echo(text)


@main.command("new-session")
@click.option("--name", default="Autosave", show_default=True)
@click.option("--seed-path", type=click.Path(exists=True, path_type=Path), default=None)
@click.pass_context
def new_session_cmd(ctx: click.Context, name: str, seed_path: Path | None) -> None:
    """Start a new active session for a world."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = create_session(
        conn,
        world_id,
        name=name,
        seed_path=str(seed_path) if seed_path else None,
    )
    click.echo(f"Started session {save.id!r} in room {save.current_room_id!r}")


@main.command("session")
@click.pass_context
def session_cmd(ctx: click.Context) -> None:
    """Show the active session for a world."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    if not save:
        raise click.ClickException(f"No active session for world {world_id!r}")
    click.echo(json.dumps(save.model_dump(), indent=2))


@main.command("list-saves")
@click.pass_context
def list_saves_cmd(ctx: click.Context) -> None:
    """List saves for a world."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    saves = list_saves(conn, world_id)
    click.echo(json.dumps(saves, indent=2, default=str))


@main.command("load")
@click.argument("name")
@click.pass_context
def load_cmd(ctx: click.Context, name: str) -> None:
    """Load a named save as the active session."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = load_session(conn, world_id, name)
    click.echo(f"Loaded save {name!r} at turn {save.turn} in {save.current_room_id!r}")


@main.command("save")
@click.argument("name")
@click.option("--overwrite", is_flag=True, help="Overwrite an existing save name")
@click.pass_context
def save_cmd(ctx: click.Context, name: str, overwrite: bool) -> None:
    """Save the active session under a name."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = save_game(conn, world_id, name, overwrite=overwrite)
    click.echo(f"Saved session as {name!r} (id={save.id})")


@main.command("play")
@click.argument("player_input")
@click.option("--json", "as_json", is_flag=True, help="Emit structured JSON result")
@click.pass_context
def play_cmd(ctx: click.Context, player_input: str, as_json: bool) -> None:
    """Apply a player command."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    if not save:
        raise click.ClickException(
            f"No active session for world {world_id!r}. Run `ta new-session` first."
        )
    result = play(conn, save, player_input)
    if as_json:
        click.echo(result.model_dump_json(indent=2))
    else:
        click.echo(result.message)
        if result.requires_agent:
            click.echo("(Agent follow-up suggested)")


@main.command("show-room")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def show_room_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show the current room."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    context = build_agent_context(conn, world_id)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "room": context.current_room,
                    "exits": context.visible_exits,
                    "items": context.visible_items,
                    "npcs": context.visible_npcs,
                },
                indent=2,
            )
        )
    else:
        room = context.current_room
        click.echo(f"{room['name']}\n{room['description']}")
        if context.visible_exits:
            click.echo("\nExits:")
            for exit_action in context.visible_exits:
                click.echo(f"  - {exit_action['label']}")
        if context.visible_items:
            click.echo("\nItems:")
            for item in context.visible_items:
                click.echo(f"  - {item['name']}")


@main.command("show-map")
@click.pass_context
def show_map_cmd(ctx: click.Context) -> None:
    """Show a simple map of known rooms."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(render_map(conn, world_id))


@main.command("context")
@click.option("--input", "player_input", default=None, help="Include candidate actions for input")
@click.option(
    "--author",
    is_flag=True,
    help="Include hidden rooms/exits for authoring (spoiler-aware agents)",
)
@click.pass_context
def context_cmd(ctx: click.Context, player_input: str | None, author: bool) -> None:
    """Emit the agent context bundle as JSON."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    perspective = "author" if author else "player"
    context = build_agent_context(
        conn, world_id, player_input=player_input, perspective=perspective
    )
    click.echo(context.model_dump_json(indent=2))


@main.command("events")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None)
@click.pass_context
def events_cmd(ctx: click.Context, output: Path | None) -> None:
    """Export the event log as JSONL."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    text = export_events_jsonl(conn, world_id, save_id=save.id if save else None)
    if output:
        output.write_text(text)
        click.echo(f"Wrote events to {output}")
    else:
        click.echo(text, nl=False)


@main.group("draft")
@click.pass_context
def draft_group(ctx: click.Context) -> None:
    """Manage world drafts."""


@draft_group.command("add")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def draft_add_cmd(ctx: click.Context, path: Path) -> None:
    """Create a draft from a JSON file."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    draft = create_draft_from_file(
        conn, world_id, path, save_id=save.id if save else None
    )
    click.echo(json.dumps(draft, indent=2, default=str))


@draft_group.command("from-narration")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def draft_from_narration_cmd(ctx: click.Context, path: Path) -> None:
    """Create a draft using the last LLM narration as source text."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    draft = create_draft_from_last_narration(
        conn, world_id, path, save_id=save.id if save else None
    )
    click.echo(json.dumps(draft, indent=2, default=str))


@draft_group.command("list")
@click.option("--all-statuses", is_flag=True, help="Include non-active drafts")
@click.pass_context
def draft_list_cmd(ctx: click.Context, all_statuses: bool) -> None:
    """List drafts for the world."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    drafts = list_drafts(conn, world_id, status=None if all_statuses else "active")
    click.echo(json.dumps(drafts, indent=2, default=str))


@draft_group.command("show")
@click.argument("draft_id")
@click.pass_context
def draft_show_cmd(ctx: click.Context, draft_id: str) -> None:
    """Show a draft by id."""
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(json.dumps(get_draft(conn, draft_id), indent=2, default=str))


@draft_group.command("revise")
@click.argument("draft_id")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def draft_revise_cmd(ctx: click.Context, draft_id: str, path: Path) -> None:
    """Replace a draft payload from JSON."""
    conn = connect(ctx.obj["db"])
    init_db(conn)
    draft = revise_draft(conn, draft_id, path)
    click.echo(json.dumps(draft, indent=2, default=str))


@draft_group.command("commit")
@click.argument("draft_id")
@click.pass_context
def draft_commit_cmd(ctx: click.Context, draft_id: str) -> None:
    """Validate and commit a draft into the world."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    try:
        result = commit_draft(
            conn, world_id, draft_id, save_id=save.id if save else None
        )
    except PatchValidationError as exc:
        raise click.ClickException("; ".join(exc.errors)) from exc
    click.echo(json.dumps(result, indent=2, default=str))


@draft_group.command("reject")
@click.argument("draft_id")
@click.pass_context
def draft_reject_cmd(ctx: click.Context, draft_id: str) -> None:
    """Reject an active draft."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    draft = reject_draft(
        conn, world_id, draft_id, save_id=save.id if save else None
    )
    click.echo(json.dumps(draft, indent=2, default=str))


@main.command("apply-patch")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def apply_patch_cmd(ctx: click.Context, path: Path) -> None:
    """Validate and apply a patch JSON file."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    save = get_active_session(conn, world_id)
    data = json.loads(path.read_text())
    if "patch" in data and "world_id" not in data["patch"]:
        data["patch"]["world_id"] = world_id
    try:
        result = apply_patch(
            conn, data, save_id=save.id if save else None
        )
    except PatchValidationError as exc:
        raise click.ClickException("; ".join(exc.errors)) from exc
    click.echo(json.dumps(result, indent=2, default=str))


@main.group("roll")
@click.pass_context
def roll_group(ctx: click.Context) -> None:
    """Engine-owned randomness."""


@roll_group.command("dice")
@click.argument("expression")
@click.option("--reason", default=None)
@click.pass_context
def roll_dice_cmd(ctx: click.Context, expression: str, reason: str | None) -> None:
    """Roll dice, e.g. 1d6+2."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(json.dumps(roll_dice(conn, world_id, expression, reason=reason), indent=2))


@roll_group.command("coin")
@click.option("--reason", default=None)
@click.pass_context
def roll_coin_cmd(ctx: click.Context, reason: str | None) -> None:
    """Flip a coin."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(json.dumps(flip_coin(conn, world_id, reason=reason), indent=2))


@roll_group.command("deck")
@click.argument("name")
@click.option("--reason", default=None)
@click.pass_context
def roll_deck_cmd(ctx: click.Context, name: str, reason: str | None) -> None:
    """Draw from a named deck in world metadata."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(json.dumps(draw_deck(conn, world_id, name, reason=reason), indent=2))


@roll_group.command("table")
@click.argument("name")
@click.option("--reason", default=None)
@click.pass_context
def roll_table_cmd(ctx: click.Context, name: str, reason: str | None) -> None:
    """Choose from a weighted table in world metadata."""
    world_id = _resolve_world(ctx)
    conn = connect(ctx.obj["db"])
    init_db(conn)
    click.echo(json.dumps(choose_table(conn, world_id, name, reason=reason), indent=2))
