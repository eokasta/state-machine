# ruff: noqa: ANN401, TC003

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


async def invoke(
    call: Callable[[Any], Any],
    context: Any,
    executor: ThreadPoolExecutor | None = None,
) -> Any:
    if inspect.iscoroutinefunction(call):
        return await call(context)
    if executor is None:
        result = await asyncio.to_thread(call, context)
    else:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, call, context)
    if inspect.isawaitable(result):
        return await result
    return result
