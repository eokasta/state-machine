# ruff: noqa: ANN401, PLR0913, PLR0917, TC003

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from state_machine.core.model.execution.substage import SubStageResult
    from state_machine.core.service.application import Application


@dataclass(frozen=True, slots=True)
class StageRetry:
    max_retries: int = 0
    interval_seconds: float = 0
    expon: float = 1
    retry_on: tuple[type[Exception], ...] = (Exception,)

    def __post_init__(self) -> None:
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if not math.isfinite(self.interval_seconds) or self.interval_seconds < 0:
            raise ValueError("interval_seconds must be finite and non-negative")
        if not math.isfinite(self.expon) or self.expon < 1:
            raise ValueError("expon must be finite and at least 1")
        if not self.retry_on or not all(
            issubclass(error, Exception) for error in self.retry_on
        ):
            raise ValueError("retry_on must contain Exception subclasses")


@dataclass(slots=True)
class StageSpec:
    target: Any
    priority: int
    concurrency: int
    retry: StageRetry | None
    name: str
    registered_order: int
    instance: bool = False


class Stage:
    def execute(self, context: StageContext) -> None:
        raise NotImplementedError


class StageContext:
    def __init__(
        self,
        app: Application,
        run_id: str,
        data: dict[str, Any],
        stage: StageSpec | None = None,
        stage_id: str | None = None,
        stage_attempt_id: str | None = None,
    ) -> None:
        self._app, self.run_id, self.data = app, run_id, data
        self._stage = stage
        self._stage_id = stage_id
        self._stage_attempt_id = stage_attempt_id

    async def amap_substage(
        self, substage: Any, items: Iterable[Any] | AsyncIterable[Any]
    ) -> SubStageResult:
        if self._stage is None or self._stage_attempt_id is None:
            raise RuntimeError(
                "substage mapping is only available while a stage executes"
            )
        return await self._app._map_substage(self, substage, items)

    def map_substage(self, substage: Any, items: Iterable[Any]) -> SubStageResult:
        return asyncio.run(self.amap_substage(substage, items))
