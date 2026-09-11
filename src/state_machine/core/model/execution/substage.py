# ruff: noqa: TC001, TC003

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any

from state_machine.core.domain.enums import AttemptStatus
from state_machine.core.model.execution.stage import StageRetry
from state_machine.core.util.json_value import JsonValue


@dataclass(slots=True)
class SubStageContext:
    run_id: str
    stage_name: str
    substage_id: str
    worker_id: int
    item_index: int
    item: Any
    attempt_number: int


@dataclass(slots=True)
class WorkerContext:
    run_id: str
    stage_name: str
    substage_id: str
    worker_id: int


class SubStage:
    """Base class for workers; lifecycle hooks are optional."""

    def setup(self, context: WorkerContext) -> None:
        """Prepare resources once for this worker."""

    def execute(self, context: SubStageContext) -> None:
        raise NotImplementedError

    def cleanup(self, context: WorkerContext) -> None:
        """Release resources once this worker has stopped."""


@dataclass(slots=True)
class SubStageSpec:
    target: Any
    retry: StageRetry | None
    name: str
    factory: bool = False


@dataclass(slots=True)
class SubStageExecutionResult:
    index: int
    status: AttemptStatus
    attempts: int
    error_type: str | None = None
    error_message: str | None = None
    context_before: JsonValue | None = None
    context_after: JsonValue | None = None


@dataclass(slots=True)
class SubStageResult:
    substage_id: str
    results: list[SubStageExecutionResult]

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def succeeded(self) -> int:
        return sum(result.status is AttemptStatus.SUCCEEDED for result in self.results)

    @property
    def failed(self) -> int:
        return sum(result.status is AttemptStatus.FAILED for result in self.results)

    def iter_results(self) -> Iterator[SubStageExecutionResult]:
        yield from sorted(self.results, key=lambda result: result.index)

    async def aiter_results(self) -> AsyncIterator[SubStageExecutionResult]:
        for result in self.iter_results():
            yield result
