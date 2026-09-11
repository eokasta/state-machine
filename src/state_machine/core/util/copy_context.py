# ruff: noqa: ANN401

from typing import Any


def copy_context(value: Any) -> Any:
    """Deep-copy public containers while keeping private values by reference."""
    if isinstance(value, dict):
        return {
            key: value
            if isinstance(key, str) and key.startswith("_")
            else copy_context(value)
            for key, value in value.items()
        }
    if isinstance(value, list):
        return [copy_context(item) for item in value]
    if isinstance(value, tuple):
        return [copy_context(item) for item in value]
    return value
