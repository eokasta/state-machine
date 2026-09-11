"""SQLAlchemy persistence for application execution history."""
# ruff: noqa: PLR0913, PLR0917, TC001, TC003

from __future__ import annotations

import traceback
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from state_machine.core.domain.enums import (
    AttemptStatus,
    RunStatus,
    StageStatus,
    SubStageStatus,
)
from state_machine.core.model.database.base import Base
from state_machine.core.model.database.run import RunRecord
from state_machine.core.model.database.stage import StageAttemptRecord, StageRecord
from state_machine.core.model.database.substage import (
    SubStageAttemptRecord,
    SubStageRecord,
)
from state_machine.core.util.json_value import JsonValue

_LEGACY_TABLES = (
    "state_machine_batches",
    "state_machine_attempts",
    "state_machine_runs",
)


class StateMachineRepository:
    def __init__(self, database_url: str) -> None:
        options: dict[str, object] = {}
        if database_url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
        self._engine = create_engine(database_url, **options)
        self._drop_legacy_tables()
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(self._engine, expire_on_commit=False)

    def close(self) -> None:
        self._engine.dispose()

    def _drop_legacy_tables(self) -> None:
        with self._engine.begin() as connection:
            existing = set(inspect(connection).get_table_names())
            for table_name in _LEGACY_TABLES:
                if table_name in existing:
                    Table(table_name, MetaData(), autoload_with=connection).drop(
                        connection
                    )

    def create_run(
        self,
        run_id: str,
        stages: Sequence[tuple[str, str, int, int, int]],
    ) -> None:
        now = _now()
        with self._session_factory.begin() as session:
            session.add(RunRecord(id=run_id, status=RunStatus.RUNNING, started_at=now))
            session.add_all(
                StageRecord(
                    id=stage_id,
                    run_id=run_id,
                    name=name,
                    priority=priority,
                    concurrency=concurrency,
                    registered_order=registered_order,
                    status=StageStatus.PENDING,
                    created_at=now,
                )
                for stage_id, name, priority, concurrency, registered_order in stages
            )

    def finish_run(self, run_id: str, status: RunStatus) -> None:
        with self._session_factory.begin() as session:
            record = session.get(RunRecord, run_id)
            if record is not None:
                result_stage_attempt_id = session.scalar(
                    select(StageAttemptRecord.id)
                    .join(
                        StageRecord,
                        StageAttemptRecord.stage_id == StageRecord.id,
                    )
                    .where(
                        StageRecord.run_id == run_id,
                        StageAttemptRecord.finished_at.is_not(None),
                    )
                    .order_by(
                        StageAttemptRecord.finished_at.desc(),
                        StageAttemptRecord.started_at.desc(),
                        StageAttemptRecord.attempt_number.desc(),
                        StageAttemptRecord.id.desc(),
                    )
                    .limit(1)
                )
                record.status = status
                record.result_stage_attempt_id = result_stage_attempt_id
                record.finished_at = _now()

    def start_stage(self, stage_id: str) -> None:
        with self._session_factory.begin() as session:
            record = session.get(StageRecord, stage_id)
            if record is not None:
                record.status, record.started_at = StageStatus.RUNNING, _now()

    def finish_stage(self, stage_id: str, status: StageStatus) -> None:
        with self._session_factory.begin() as session:
            record = session.get(StageRecord, stage_id)
            if record is not None:
                record.status, record.finished_at = status, _now()

    def start_stage_attempt(
        self,
        attempt_id: str,
        stage_id: str,
        number: int,
        before: JsonValue,
    ) -> None:
        with self._session_factory.begin() as session:
            session.add(
                StageAttemptRecord(
                    id=attempt_id,
                    stage_id=stage_id,
                    attempt_number=number,
                    status=AttemptStatus.RUNNING,
                    context_before=before,
                    started_at=_now(),
                )
            )

    def finish_stage_attempt(
        self,
        attempt_id: str,
        status: AttemptStatus,
        after: JsonValue | None,
        error: Exception | None,
    ) -> None:
        with self._session_factory.begin() as session:
            record = session.get(StageAttemptRecord, attempt_id)
            if record is not None:
                _finish_attempt(record, status, after, error)

    def create_substage(
        self, substage_id: str, stage_attempt_id: str, name: str
    ) -> None:
        with self._session_factory.begin() as session:
            session.add(
                SubStageRecord(
                    id=substage_id,
                    stage_attempt_id=stage_attempt_id,
                    name=name,
                    status=SubStageStatus.RUNNING,
                    started_at=_now(),
                )
            )

    def finish_substage(self, substage_id: str, status: SubStageStatus) -> None:
        with self._session_factory.begin() as session:
            record = session.get(SubStageRecord, substage_id)
            if record is not None:
                record.status, record.finished_at = status, _now()

    def start_substage_attempt(
        self,
        attempt_id: str,
        substage_id: str,
        item_index: int,
        worker_id: int,
        number: int,
        before: JsonValue,
    ) -> None:
        with self._session_factory.begin() as session:
            session.add(
                SubStageAttemptRecord(
                    id=attempt_id,
                    substage_id=substage_id,
                    item_index=item_index,
                    worker_id=worker_id,
                    attempt_number=number,
                    status=AttemptStatus.RUNNING,
                    context_before=before,
                    started_at=_now(),
                )
            )

    def finish_substage_attempt(
        self,
        attempt_id: str,
        status: AttemptStatus,
        after: JsonValue | None,
        error: Exception | None,
    ) -> None:
        with self._session_factory.begin() as session:
            record = session.get(SubStageAttemptRecord, attempt_id)
            if record is not None:
                _finish_attempt(record, status, after, error)

    def abandon_stage_attempt(self, attempt_id: str) -> None:
        self.finish_stage_attempt(attempt_id, AttemptStatus.ABANDONED, None, None)

    def terminate_substage(self, substage_id: str, status: SubStageStatus) -> None:
        with self._session_factory.begin() as session:
            for attempt in session.scalars(
                select(SubStageAttemptRecord).where(
                    SubStageAttemptRecord.substage_id == substage_id,
                    SubStageAttemptRecord.status == AttemptStatus.RUNNING,
                )
            ):
                _finish_attempt(attempt, AttemptStatus.ABANDONED, None, None)
            record = session.get(SubStageRecord, substage_id)
            if record is not None:
                record.status, record.finished_at = status, _now()


def _finish_attempt(
    record: StageAttemptRecord | SubStageAttemptRecord,
    status: AttemptStatus,
    after: JsonValue | None,
    error: Exception | None,
) -> None:
    record.status, record.context_after, record.finished_at = status, after, _now()
    if error is not None:
        record.error_type, record.error_message = type(error).__name__, str(error)
        record.error_traceback = "".join(traceback.format_exception(error))


def _now() -> datetime:
    return datetime.now(UTC)
