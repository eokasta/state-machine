# ruff: noqa: ANN401, PLR0912, TC001

from __future__ import annotations

import math
from typing import Any, cast

from state_machine.core.util.json_value import JsonValue


def public_snapshot(value: Any, seen: set[int] | None = None) -> JsonValue:
    """Copy JSON data while omitting private dictionary entries."""
    if seen is None:
        seen = set()
    if value is None or isinstance(value, (bool, str, int)):
        return cast("JsonValue", value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("context contains a non-finite float")
        return value
    if isinstance(value, dict):
        marker = id(value)
        if marker in seen:
            raise ValueError("context contains a public cycle")
        seen.add(marker)
        try:
            result: dict[str, JsonValue] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("context keys must be strings")
                if not key.startswith("_"):
                    result[key] = public_snapshot(item, seen)
            return result
        finally:
            seen.remove(marker)
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in seen:
            raise ValueError("context contains a public cycle")
        seen.add(marker)
        try:
            return [public_snapshot(item, seen) for item in value]
        finally:
            seen.remove(marker)
    raise ValueError(f"context contains non-JSON value {type(value).__name__}")
