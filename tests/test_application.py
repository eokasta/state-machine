# ruff: noqa: E501, PLR2004, TC003

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

import state_machine as sm


def app_at(path: Path) -> sm.Application:
    return sm.Application(config=sm.ApplicationConfig(database_url=f"sqlite:///{path}"))


def schema_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as database:
        return {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row[0].startswith("sqlite_")
        }


def test_new_schema_has_only_execution_tables_and_foreign_keys(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app_at(path).close()

    assert schema_names(path) == {
        "sm_runs",
        "sm_stages",
        "sm_stage_attempts",
        "sm_substages",
        "sm_substage_attempts",
    }
    with sqlite3.connect(path) as database:
        run_columns = {
            row[1]: row
            for row in database.execute("PRAGMA table_info(sm_runs)").fetchall()
        }
        run_foreign_keys = database.execute(
            "PRAGMA foreign_key_list(sm_runs)"
        ).fetchall()
        run_indexes = database.execute("PRAGMA index_list(sm_runs)").fetchall()
        assert "result_stage_attempt_id" in run_columns
        assert run_columns["result_stage_attempt_id"][3] == 0
        assert any(
            foreign_key[2] == "sm_stage_attempts"
            and foreign_key[3] == "result_stage_attempt_id"
            and foreign_key[4] == "id"
            for foreign_key in run_foreign_keys
        )
        assert any(
            index[1] == "ix_sm_runs_result_stage_attempt_id" for index in run_indexes
        )
        assert (
            database.execute("PRAGMA foreign_key_list(sm_stages)").fetchone()[2]
            == "sm_runs"
        )
        assert (
            database.execute("PRAGMA foreign_key_list(sm_stage_attempts)").fetchone()[2]
            == "sm_stages"
        )
        assert (
            database.execute("PRAGMA foreign_key_list(sm_substages)").fetchone()[2]
            == "sm_stage_attempts"
        )
        assert (
            database.execute(
                "PRAGMA foreign_key_list(sm_substage_attempts)"
            ).fetchone()[2]
            == "sm_substages"
        )


def test_legacy_tables_are_replaced_automatically(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as database:
        database.execute("CREATE TABLE state_machine_runs (id TEXT PRIMARY KEY)")
        database.execute("CREATE TABLE state_machine_attempts (id TEXT PRIMARY KEY)")
        database.execute("CREATE TABLE state_machine_batches (id TEXT PRIMARY KEY)")

    app_at(path).close()

    assert schema_names(path) == {
        "sm_runs",
        "sm_stages",
        "sm_stage_attempts",
        "sm_substages",
        "sm_substage_attempts",
    }


def test_function_stages_are_ordered_and_persist_snapshots(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    seen: list[int] = []

    @app.stage(priority=2)
    def second(context: sm.StageContext) -> None:
        seen.append(2)
        context.data["second"] = True

    @app.stage(priority=1)
    def first(context: sm.StageContext) -> None:
        seen.append(1)
        context.data["first"] = True

    result = app.run(data={"input": 1})
    assert seen == [1, 2]
    assert result.data == {"input": 1, "first": True, "second": True}

    with sqlite3.connect(path) as database:
        snapshots = database.execute(
            "SELECT context_before, context_after FROM sm_stage_attempts ORDER BY started_at"
        ).fetchall()
        stages = database.execute(
            "SELECT status FROM sm_stages ORDER BY registered_order"
        ).fetchall()
        run_result = database.execute(
            """
            SELECT stage.name, attempt.status
            FROM sm_runs AS run
            JOIN sm_stage_attempts AS attempt
                ON attempt.id = run.result_stage_attempt_id
            JOIN sm_stages AS stage ON stage.id = attempt.stage_id
            """
        ).fetchone()
    assert '"input": 1' in snapshots[0][0]
    assert '"first": true' in snapshots[0][1]
    assert stages == [("SUCCEEDED",), ("SUCCEEDED",)]
    assert run_result[0].endswith(".second")
    assert run_result[1] == "SUCCEEDED"


def test_all_stages_are_materialized_and_unreached_stages_stay_pending(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    @app.stage(priority=0)
    def failing(_: sm.StageContext) -> None:
        raise RuntimeError("stop")

    @app.stage(priority=1)
    def never(_: sm.StageContext) -> None:
        raise AssertionError("not reached")

    with pytest.raises(RuntimeError, match="stop"):
        app.run()

    with sqlite3.connect(path) as database:
        rows = database.execute(
            "SELECT status FROM sm_stages ORDER BY registered_order"
        ).fetchall()
        run_result = database.execute(
            """
            SELECT attempt.status, attempt.error_type, attempt.error_message,
                attempt.error_traceback
            FROM sm_runs AS run
            JOIN sm_stage_attempts AS attempt
                ON attempt.id = run.result_stage_attempt_id
            """
        ).fetchone()
    assert rows == [("FAILED",), ("PENDING",)]
    assert run_result[:3] == ("FAILED", "RuntimeError", "stop")
    assert "RuntimeError: stop" in run_result[3]


def test_class_stage_executes_and_is_persisted(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    @app.stage()
    class Prepare(sm.Stage):
        def execute(self, context: sm.StageContext) -> None:
            context.data["prepared"] = True

    result = app.run()

    assert result.data == {"prepared": True}
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT status FROM sm_stages").fetchone() == (
            "SUCCEEDED",
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_retries": -1}, "max_retries"),
        ({"interval_seconds": float("inf")}, "interval_seconds"),
        ({"expon": 0.5}, "expon"),
        ({"retry_on": ()}, "retry_on"),
    ],
)
def test_stage_retry_rejects_invalid_configuration(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        sm.StageRetry(**kwargs)  # type: ignore[arg-type]


def test_stage_registration_rejects_invalid_concurrency_and_duplicates(
    tmp_path: Path,
) -> None:
    app = app_at(tmp_path / "history.db")

    with pytest.raises(ValueError, match="concurrency must be positive"):
        app.stage(concurrency=0)(lambda _: None)

    def stage(_: sm.StageContext) -> None:
        pass

    app.stage()(stage)
    with pytest.raises(ValueError, match="stage already registered"):
        app.stage()(stage)


def test_run_result_points_to_successful_attempt_after_retry(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    calls = 0

    @app.stage(retry=sm.StageRetry(max_retries=1))
    def flaky(_: sm.StageContext) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("try again")

    app.run()

    with sqlite3.connect(path) as database:
        attempts = database.execute(
            "SELECT id, attempt_number, status FROM sm_stage_attempts "
            "ORDER BY attempt_number"
        ).fetchall()
        result_id = database.execute(
            "SELECT result_stage_attempt_id FROM sm_runs"
        ).fetchone()[0]

    assert [(number, status) for _, number, status in attempts] == [
        (1, "FAILED"),
        (2, "SUCCEEDED"),
    ]
    assert result_id == attempts[1][0]


def test_run_without_stages_has_no_result_attempt(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    app.run()

    with sqlite3.connect(path) as database:
        run = database.execute(
            "SELECT status, result_stage_attempt_id FROM sm_runs"
        ).fetchone()

    assert run == ("SUCCEEDED", None)


def test_run_failing_before_first_attempt_has_no_result_attempt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    @app.stage()
    def stage(_: sm.StageContext) -> None:
        raise AssertionError("stage should not execute")

    with pytest.raises(ValueError, match="non-JSON value object"):
        app.run(data={"invalid": object()})

    with sqlite3.connect(path) as database:
        run = database.execute(
            "SELECT status, result_stage_attempt_id FROM sm_runs"
        ).fetchone()
        attempt_count = database.execute(
            "SELECT COUNT(*) FROM sm_stage_attempts"
        ).fetchone()[0]

    assert run == ("FAILED", None)
    assert attempt_count == 0


def test_private_values_are_available_but_not_serialized(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    driver = object()

    @app.stage()
    def stage(context: sm.StageContext) -> None:
        assert context.data["_driver"] is driver
        context.data["nested"] = {"_resource": object(), "ok": True}

    app.run(data={"_driver": driver, "public": "value"})
    with sqlite3.connect(path) as database:
        before, after = database.execute(
            "SELECT context_before, context_after FROM sm_stage_attempts"
        ).fetchone()
    assert "_driver" not in before
    assert "_resource" not in after
    assert '"ok": true' in after


def test_substages_have_one_record_per_call_and_one_lifecycle_per_worker(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    lifecycle: list[tuple[str, int, str]] = []

    @app.substage()
    class Worker(sm.SubStage):
        def setup(self, context: sm.WorkerContext) -> None:
            lifecycle.append(("setup", context.worker_id, context.substage_id))

        async def execute(self, context: sm.SubStageContext) -> None:
            context.item["done"] = True

        def cleanup(self, context: sm.WorkerContext) -> None:
            lifecycle.append(("cleanup", context.worker_id, context.substage_id))

    @app.stage(concurrency=2)
    async def stage(context: sm.StageContext) -> None:
        result = await context.amap_substage(Worker, [{"n": 1}, {"n": 2}, {"n": 3}])
        context.data["substage_id"] = result.substage_id
        context.data["succeeded"] = result.succeeded

    result = asyncio.run(app.arun())
    assert result.data["succeeded"] == 3
    assert len({entry[2] for entry in lifecycle}) == 1
    assert sorted((action, worker) for action, worker, _ in lifecycle) == [
        ("cleanup", 0),
        ("cleanup", 1),
        ("setup", 0),
        ("setup", 1),
    ]
    with sqlite3.connect(path) as database:
        substages = database.execute("SELECT id, status FROM sm_substages").fetchall()
        attempts = database.execute(
            "SELECT item_index, attempt_number FROM sm_substage_attempts ORDER BY item_index"
        ).fetchall()
    assert substages == [(result.data["substage_id"], "SUCCEEDED")]
    assert attempts == [(0, 1), (1, 1), (2, 1)]


def test_substage_failures_retry_without_failing_aggregate_substage(
    tmp_path: Path,
) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    calls: dict[int, int] = {}
    captured: list[sm.SubStageResult] = []

    @app.substage(retry=sm.StageRetry(max_retries=1))
    def process(context: sm.SubStageContext) -> None:
        calls[context.item] = calls.get(context.item, 0) + 1
        if context.item == 2:
            raise ValueError("bad item")

    @app.stage(concurrency=2)
    def stage(context: sm.StageContext) -> None:
        result = context.map_substage(process, [1, 2, 3])
        captured.append(result)

    app.run()
    substage_result = captured[0]
    assert isinstance(substage_result, sm.SubStageResult)
    assert substage_result.succeeded == 2
    assert substage_result.failed == 1
    assert calls == {1: 1, 2: 2, 3: 1}
    with sqlite3.connect(path) as database:
        status = database.execute("SELECT status FROM sm_substages").fetchone()[0]
        attempts = database.execute(
            "SELECT item_index, attempt_number, status FROM sm_substage_attempts ORDER BY item_index, attempt_number"
        ).fetchall()
    assert status == "SUCCEEDED"
    assert attempts == [
        (0, 1, "SUCCEEDED"),
        (1, 1, "FAILED"),
        (1, 2, "FAILED"),
        (2, 1, "SUCCEEDED"),
    ]


def test_empty_substage_mapping_succeeds_without_attempts(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)
    captured: list[sm.SubStageResult] = []

    @app.substage()
    def process(_: sm.SubStageContext) -> None:
        raise AssertionError("no item should be processed")

    @app.stage()
    def stage(context: sm.StageContext) -> None:
        captured.append(context.map_substage(process, []))

    app.run()

    assert captured[0].total == 0
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT status FROM sm_substages").fetchone() == (
            "SUCCEEDED",
        )
        assert database.execute(
            "SELECT COUNT(*) FROM sm_substage_attempts"
        ).fetchone() == (0,)


def test_cancelling_a_substage_marks_all_open_records_cancelled(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    async def scenario() -> None:
        started = asyncio.Event()
        never_finishes = asyncio.Event()

        @app.substage()
        async def process(_: sm.SubStageContext) -> None:
            started.set()
            await never_finishes.wait()

        @app.stage()
        async def stage(context: sm.StageContext) -> None:
            await context.amap_substage(process, [1])

        task = asyncio.create_task(app.arun())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    with sqlite3.connect(path) as database:
        run = database.execute(
            "SELECT status, result_stage_attempt_id FROM sm_runs"
        ).fetchone()
        assert database.execute("SELECT status FROM sm_stages").fetchone() == (
            "CANCELLED",
        )
        stage_attempt = database.execute(
            "SELECT id, status FROM sm_stage_attempts"
        ).fetchone()
        assert database.execute("SELECT status FROM sm_substages").fetchone() == (
            "CANCELLED",
        )
        assert database.execute(
            "SELECT status FROM sm_substage_attempts"
        ).fetchone() == ("ABANDONED",)
    assert run == ("CANCELLED", stage_attempt[0])
    assert stage_attempt[1] == "ABANDONED"


def test_structural_substage_failure_marks_substage_failed(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    app = app_at(path)

    @app.substage()
    class Broken(sm.SubStage):
        def setup(self, _: sm.WorkerContext) -> None:
            raise RuntimeError("setup failed")

    @app.stage()
    def stage(context: sm.StageContext) -> None:
        context.map_substage(Broken, [1])

    with pytest.raises(RuntimeError, match="setup failed"):
        app.run()
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT status FROM sm_substages").fetchone() == (
            "FAILED",
        )


def test_public_api_exposes_only_new_result_names() -> None:
    assert sm.SubStageResult is not None
    assert sm.SubStageExecutionResult is not None
    assert not hasattr(sm, "SubStageBatchResult")
    assert not hasattr(sm, "SubStageItemResult")
