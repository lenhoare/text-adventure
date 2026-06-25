"""Standalone CLI entry points wrapping the main Click commands."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from engine.cli import main

GLOBAL_OPTION_FLAGS = ("--db", "--world")


def _partition_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """Move group-level options before the subcommand name."""
    global_args: list[str] = []
    command_args: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in GLOBAL_OPTION_FLAGS:
            global_args.append(arg)
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                global_args.append(argv[i + 1])
                i += 2
                continue
            i += 1
            continue
        if arg.startswith("--db=") or arg.startswith("--world="):
            global_args.append(arg)
            i += 1
            continue
        command_args.append(arg)
        i += 1
    return global_args, command_args


def _run_command(
    subcommand: str,
    *,
    require_args: bool = False,
    usage: str | None = None,
) -> None:
    global_args, command_args = _partition_argv(sys.argv[1:])
    script = Path(sys.argv[0]).name

    if require_args and not command_args:
        click.echo(
            usage or f"Usage: {script} [--world ID] [--db PATH] <arguments>",
            err=True,
        )
        click.echo(
            f"Example: {script} --world house_by_sea \"look\"",
            err=True,
        )
        raise SystemExit(2)

    args = [*global_args, subcommand, *command_args]
    try:
        main(args, standalone_mode=False)
    except click.exceptions.MissingParameter:
        click.echo(
            usage or f"Usage: {script} [--world ID] [--db PATH] <arguments>",
            err=True,
        )
        raise SystemExit(2) from None
    except SystemExit as exc:
        raise SystemExit(exc.code) from None


def play_cmd() -> None:
    _run_command(
        "play",
        require_args=True,
        usage='ta-play [--world ID] [--json] "<player input>"',
    )


def show_room_cmd() -> None:
    _run_command("show-room")


def show_map_cmd() -> None:
    _run_command("show-map")


def save_cmd() -> None:
    _run_command(
        "save",
        require_args=True,
        usage="ta-save [--world ID] [--overwrite] <save name>",
    )


def load_cmd() -> None:
    _run_command(
        "load",
        require_args=True,
        usage="ta-load [--world ID] <save name>",
    )


def export_cmd() -> None:
    _run_command("export")


def import_cmd() -> None:
    _run_command(
        "import",
        require_args=True,
        usage="ta-import <seed.json>",
    )


def context_cmd() -> None:
    _run_command("context")


def new_session_cmd() -> None:
    _run_command("new-session")


def session_cmd() -> None:
    _run_command("session")


def draft_cmd() -> None:
    _run_command("draft", usage="ta-draft [--world ID] <subcommand> ...")


def apply_patch_cmd() -> None:
    _run_command(
        "apply-patch",
        require_args=True,
        usage="ta-apply-patch [--world ID] <patch.json>",
    )


def roll_cmd() -> None:
    _run_command("roll", usage="ta-roll [--world ID] <subcommand> ...")
