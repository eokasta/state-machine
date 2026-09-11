# ruff: noqa: ANN401

from __future__ import annotations

import inspect
from typing import Any


def name_of(target: Any) -> str:
    subject = target
    if inspect.isclass(subject) or inspect.isfunction(subject):
        return f"{subject.__module__}.{subject.__qualname__}"
    return f"{subject.__class__.__module__}.{subject.__class__.__qualname__}"
