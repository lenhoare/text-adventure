from __future__ import annotations

import re
from typing import Any

REQUIRES_PATTERN = re.compile(
    r"^(!)?(flags|inventory)\.([a-zA-Z0-9_]+)$"
)


class RequiresError(ValueError):
    pass


def parse_requirement(expr: str) -> tuple[bool, str, str]:
    match = REQUIRES_PATTERN.match(expr.strip())
    if not match:
        raise RequiresError(f"Invalid requirement expression: {expr!r}")
    negated = match.group(1) == "!"
    namespace = match.group(2)
    name = match.group(3)
    return negated, namespace, name


def evaluate_requirements(
    requirements: list[str],
    *,
    flags: dict[str, Any],
    inventory: list[str],
) -> tuple[bool, str | None]:
    inventory_set = set(inventory)
    for expr in requirements:
        negated, namespace, name = parse_requirement(expr)
        if namespace == "flags":
            value = bool(flags.get(name))
        elif namespace == "inventory":
            value = name in inventory_set
        else:
            raise RequiresError(f"Unknown namespace in {expr!r}")

        satisfied = not value if negated else value
        if not satisfied:
            return False, expr
    return True, None


def apply_effects(
    effects: dict[str, Any],
    *,
    flags: dict[str, Any],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    set_flags = effects.get("set_flags")
    if isinstance(set_flags, dict):
        for key, value in set_flags.items():
            flags[key] = value
            changes.append({"op": "set_flag", "flag": key, "value": value})
    return changes
