"""Application runtime for stages, substages, retries, and persistence."""
# ruff: noqa: ANN401, PLR0913, PLR0915, PLR0917, TC001, TC003

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar, cast

from state_machine.core.domain.enums import (
    AttemptStatus,
    RunStatus,
    StageStatus,
    SubStageStatus,
)
from state_machine.core.model.execution.application_config import ApplicationConfig
from state_machine.core.model.execution.stage import StageContext, StageRetry, StageSpec
from state_machine.core.model.execution.substage import (
    SubStageContext,
    SubStageExecutionResult,
    SubStageResult,
    SubStageSpec,
    WorkerContext,
)
from state_machine.core.service.repository import StateMachineRepository
from state_machine.core.util.copy_context import copy_context
from state_machine.core.util.invoke import invoke
from state_machine.core.util.name import name_of
from state_machine.core.util.public_snapshot import public_snapshot

T = TypeVar("T")


class Application:
    def __init__(self, *, config: ApplicationConfig) -> None:
        self.config = config
        self._repository = StateMachineRepository(config.database_url)
        self._stages: list[StageSpec] = []
        self._substages: dict[Any, SubStageSpec] = {}
        self._registered: set[str] = set()

    def close(self) -> None:
        self._repository.close()

    def stage(
        self,
        *,
        priority: int = 0,
        concurrency: int = 1,
        retry: StageRetry | None = None,
    ) -> Callable[[T], T]:
        def register(target: T) -> T:
            self._register_stage(target, priority, concurrency, retry, False)
            return target

        return register

    def add_stage(
        self,
        instance: Any,
        *,
        priority: int = 0,
        concurrency: int = 1,
        retry: StageRetry | None = None,
    ) -> None:
        self._register_stage(instance, priority, concurrency, retry, True)

    def _register_stage(
        self,
        target: Any,
        priority: int,
        concurrency: int,
        retry: StageRetry | None,
        instance: bool,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        name = name_of(target)
        if name in self._registered:
            raise ValueError(f"stage already registered: {name}")
        self._registered.add(name)
        self._stages.append(
            StageSpec(
                target, priority, concurrency, retry, name, len(self._stages), instance
            )
        )

    def substage(self, *, retry: StageRetry | None = None) -> Callable[[T], T]:
        def register(target: T) -> T:
            self._register_substage(target, retry, False)
            return target

        return register

    def add_substage(
        self, factory: Callable[[], Any], *, retry: StageRetry | None = None
    ) -> Callable[[], Any]:
        self._register_substage(factory, retry, True)
        return factory

    def _register_substage(
        self, target: Any, retry: StageRetry | None, factory: bool
    ) -> None:
        if target in self._substages:
            raise ValueError(f"substage already registered: {name_of(target)}")
        self._substages[target] = SubStageSpec(target, retry, name_of(target), factory)

    def run(self, *, data: dict[str, Any] | None = None) -> StageContext:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(data=data))
        raise RuntimeError(
            "Application.run cannot be used in an event loop; use await arun(...)"
        )

    async def arun(self, *, data: dict[str, Any] | None = None) -> StageContext:
        context = StageContext(self, str(uuid.uuid4()), copy_context(data or {}))
        stage_entries = [(str(uuid.uuid4()), spec) for spec in self._stages]
        await asyncio.to_thread(
            self._repository.create_run,
            context.run_id,
            [
                (
                    stage_id,
                    spec.name,
                    spec.priority,
                    spec.concurrency,
                    spec.registered_order,
                )
                for stage_id, spec in stage_entries
            ],
        )
        try:
            for stage_id, spec in sorted(
                stage_entries,
                key=lambda item: (item[1].priority, item[1].registered_order),
            ):
                await self._execute_stage(context, stage_id, spec)
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self._repository.finish_run, context.run_id, RunStatus.CANCELLED
            )
            raise
        except BaseException:
            await asyncio.to_thread(
                self._repository.finish_run, context.run_id, RunStatus.FAILED
            )
            raise
        await asyncio.to_thread(
            self._repository.finish_run, context.run_id, RunStatus.SUCCEEDED
        )
        return context

    async def _execute_stage(
        self, context: StageContext, stage_id: str, spec: StageSpec
    ) -> None:
        attempt_id: str | None = None
        await asyncio.to_thread(self._repository.start_stage, stage_id)
        try:
            target = (
                spec.target
                if spec.instance
                else (spec.target() if inspect.isclass(spec.target) else spec.target)
            )
            call = getattr(target, "execute", target)
            retry = spec.retry or StageRetry()
            for number in range(1, retry.max_retries + 2):
                before = public_snapshot(context.data)
                attempt_id = str(uuid.uuid4())
                await asyncio.to_thread(
                    self._repository.start_stage_attempt,
                    attempt_id,
                    stage_id,
                    number,
                    before,
                )
                active = StageContext(
                    self, context.run_id, context.data, spec, stage_id, attempt_id
                )
                try:
                    await invoke(cast("Callable[[Any], Any]", call), active)
                    after = public_snapshot(context.data)
                except Exception as error:
                    after = _safe_snapshot(context.data)
                    await asyncio.to_thread(
                        self._repository.finish_stage_attempt,
                        attempt_id,
                        AttemptStatus.FAILED,
                        after,
                        error,
                    )
                    attempt_id = None
                    if number <= retry.max_retries and isinstance(
                        error, retry.retry_on
                    ):
                        await asyncio.sleep(
                            retry.interval_seconds * retry.expon ** (number - 1)
                        )
                        continue
                    raise
                await asyncio.to_thread(
                    self._repository.finish_stage_attempt,
                    attempt_id,
                    AttemptStatus.SUCCEEDED,
                    after,
                    None,
                )
                attempt_id = None
                await asyncio.to_thread(
                    self._repository.finish_stage, stage_id, StageStatus.SUCCEEDED
                )
                return
        except asyncio.CancelledError:
            if attempt_id is not None:
                await asyncio.to_thread(
                    self._repository.abandon_stage_attempt, attempt_id
                )
            await asyncio.to_thread(
                self._repository.finish_stage, stage_id, StageStatus.CANCELLED
            )
            raise
        except BaseException:
            await asyncio.to_thread(
                self._repository.finish_stage, stage_id, StageStatus.FAILED
            )
            raise

    async def _map_substage(
        self,
        parent: StageContext,
        target: Any,
        items: Iterable[Any] | AsyncIterable[Any],
    ) -> SubStageResult:
        spec = self._substages.get(target)
        if spec is None:
            raise ValueError("substage is not registered with this application")
        substage_id = str(uuid.uuid4())
        await asyncio.to_thread(
            self._repository.create_substage,
            substage_id,
            cast("str", parent._stage_attempt_id),
            spec.name,
        )
        stage = parent._stage
        assert stage is not None
        count = stage.concurrency
        queue: asyncio.Queue[tuple[int, Any] | None] = asyncio.Queue(maxsize=count)
        results: list[SubStageExecutionResult] = []
        lock = asyncio.Lock()

        async def source() -> AsyncIterator[Any]:
            if hasattr(items, "__aiter__"):
                async for item in cast("AsyncIterable[Any]", items):
                    yield item
            else:
                for item in items:
                    yield item

        async def producer() -> None:
            index = 0
            async for item in source():
                await queue.put((index, copy_context(item)))
                index += 1
            for _ in range(count):
                await queue.put(None)

        async def worker(worker_id: int) -> None:
            instance = (
                spec.target()
                if (inspect.isclass(spec.target) or spec.factory)
                else spec.target
            )
            worker_context = WorkerContext(
                parent.run_id, stage.name, substage_id, worker_id
            )
            setup = getattr(instance, "setup", None)
            cleanup = getattr(instance, "cleanup", None)
            with ThreadPoolExecutor(max_workers=1) as executor:
                if setup is not None:
                    await invoke(setup, worker_context, executor)
                try:
                    while (entry := await queue.get()) is not None:
                        index, item = entry
                        result = await self._execute_substage_item(
                            parent,
                            spec,
                            instance,
                            worker_context,
                            index,
                            item,
                            executor,
                        )
                        async with lock:
                            results.append(result)
                finally:
                    if cleanup is not None:
                        await invoke(cleanup, worker_context, executor)

        tasks = [
            asyncio.create_task(producer()),
            *(asyncio.create_task(worker(worker_id)) for worker_id in range(count)),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            await _cancel_tasks(tasks)
            await asyncio.to_thread(
                self._repository.terminate_substage,
                substage_id,
                SubStageStatus.CANCELLED,
            )
            raise
        except BaseException:
            await _cancel_tasks(tasks)
            await asyncio.to_thread(
                self._repository.terminate_substage,
                substage_id,
                SubStageStatus.FAILED,
            )
            raise
        await asyncio.to_thread(
            self._repository.finish_substage, substage_id, SubStageStatus.SUCCEEDED
        )
        return SubStageResult(substage_id, results)

    async def _execute_substage_item(
        self,
        parent: StageContext,
        spec: SubStageSpec,
        instance: Any,
        worker: WorkerContext,
        index: int,
        item: Any,
        executor: ThreadPoolExecutor,
    ) -> SubStageExecutionResult:
        retry = spec.retry or StageRetry()
        call = getattr(instance, "execute", instance)
        for number in range(1, retry.max_retries + 2):
            before = public_snapshot(item)
            attempt_id = str(uuid.uuid4())
            await asyncio.to_thread(
                self._repository.start_substage_attempt,
                attempt_id,
                worker.substage_id,
                index,
                worker.worker_id,
                number,
                before,
            )
            context = SubStageContext(
                parent.run_id,
                parent._stage.name if parent._stage else "",
                worker.substage_id,
                worker.worker_id,
                index,
                item,
                number,
            )
            try:
                await invoke(call, context, executor)
                after = public_snapshot(item)
            except asyncio.CancelledError:
                await asyncio.to_thread(
                    self._repository.finish_substage_attempt,
                    attempt_id,
                    AttemptStatus.ABANDONED,
                    None,
                    None,
                )
                raise
            except Exception as error:
                after = _safe_snapshot(item)
                await asyncio.to_thread(
                    self._repository.finish_substage_attempt,
                    attempt_id,
                    AttemptStatus.FAILED,
                    after,
                    error,
                )
                if number <= retry.max_retries and isinstance(error, retry.retry_on):
                    await asyncio.sleep(
                        retry.interval_seconds * retry.expon ** (number - 1)
                    )
                    continue
                return SubStageExecutionResult(
                    index,
                    AttemptStatus.FAILED,
                    number,
                    type(error).__name__,
                    str(error),
                    before,
                    after,
                )
            await asyncio.to_thread(
                self._repository.finish_substage_attempt,
                attempt_id,
                AttemptStatus.SUCCEEDED,
                after,
                None,
            )
            return SubStageExecutionResult(
                index,
                AttemptStatus.SUCCEEDED,
                number,
                context_before=before,
                context_after=after,
            )
        raise AssertionError("unreachable")


def _safe_snapshot(value: Any) -> Any:
    try:
        return public_snapshot(value)
    except ValueError:
        return None


async def _cancel_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
