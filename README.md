# State Machine

A Python library for executing multi-step workflows with retries, concurrent item
processing, execution context, and a durable history in SQLAlchemy-compatible
databases.

## What the project does

`state-machine` coordinates an application run as an ordered pipeline of
**stages**. A stage may be synchronous or asynchronous, can be retried after
eligible failures, and receives a shared execution context.

Inside a stage, a **substage** maps the same operation over many input items.
Items run concurrently up to the configured concurrency limit and can be retried
independently. A failed item is returned in the mapping result; it only fails the
parent stage when the stage explicitly raises an error. Setup, cleanup, or mapping
failures are structural failures and fail the substage.

Every relevant execution is persisted:

```text
run → stages → stage attempts → substages → substage item attempts
```

The public API exposes lifecycle enums for each level: `RunStatus`,
`StageStatus`, `SubStageStatus`, and `AttemptStatus`. They define and validate
the allowed status transitions. Context snapshots, errors, timestamps, retry
numbers, priority, and concurrency are recorded so a completed or interrupted
run can be inspected afterwards.

### Run lifecycle

| Current status | Allowed next statuses |
| --- | --- |
| `PENDING` | `RUNNING`, `CANCELLED` |
| `RUNNING` | `SUCCEEDED`, `FAILED`, `RETRY_PENDING`, `CANCELLED` |
| `RETRY_PENDING` | `RUNNING`, `DEAD_LETTER`, `CANCELLED` |
| `FAILED` | `RETRY_PENDING`, `DEAD_LETTER` |
| `SUCCEEDED` | — |
| `CANCELLED` | — |
| `DEAD_LETTER` | — |

An attempt starts in `RUNNING` and can transition to `SUCCEEDED`, `FAILED`,
or `ABANDONED`. All other attempt states are terminal.

## Stack

- **Python 3.12+**
- **uv** for environment, dependency, and build management
- **uv_build** as the packaging backend
- **pytest** for testing
- **Ruff** for linting and formatting
- **mypy** in strict mode for static type checking

## Project structure

```text
.
├── src/
│   └── state_machine/
│       ├── api/                 # Reserved for the public API
│       └── core/
│           └── domain/
│               └── enums.py     # States and transition rules
├── tests/
│   └── test_enums.py            # Transition tests
├── pyproject.toml               # Project metadata and tool configuration
└── uv.lock                      # Dependency lockfile
```

## Getting started

Install [uv](https://docs.astral.sh/uv/) and synchronize the environment from the
repository root:

```bash
uv sync --all-groups
```

## Development

Run the tests:

```bash
uv run pytest
```

Check style and static issues:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## Usage example

```python
from state_machine.api import RunStatus

current_status = RunStatus.PENDING

if current_status.can_transition_to(RunStatus.RUNNING):
    current_status = RunStatus.RUNNING
```

## Possible next steps

The project already establishes the domain rules. Natural next steps include
exposing a public API, adding entities for runs and attempts, persisting transition
history, and integrating with task queues or orchestration systems.

## Application pipeline

The public API executes registered stages in priority order and stores run history
in the configured SQLAlchemy database. Import from `state_machine.api`, or use
the equivalent `import state_machine as sm` shortcut.

```python
import state_machine as sm

app = sm.Application(
    config=sm.ApplicationConfig(database_url="sqlite:///state-machine.db")
)


@app.stage(priority=0)
def prepare(context: sm.StageContext) -> None:
    context.data["ready"] = True


context = app.run(data={"source": "example"})
```

Stages can be functions or classes with `execute(context)`. `async def` stages
are supported with `await app.arun(...)`. Use `StageRetry` to retry a stage after
an eligible exception.

## Example scenarios

The examples in [`examples/`](examples/) progress from the minimum setup to a
workflow with concurrent processing and per-item failure handling:

1. [`01_first_stage.py`](examples/01_first_stage.py): one stage and context data.
2. [`02_pipeline_and_context.py`](examples/02_pipeline_and_context.py): priority
   ordering and shared context.
3. [`03_stage_retry.py`](examples/03_stage_retry.py): retry after a transient
   failure.
4. [`04_concurrent_substage.py`](examples/04_concurrent_substage.py): concurrent
   substage processing with per-item retries.
5. [`05_complete_workflow.py`](examples/05_complete_workflow.py): workers,
   partial results, and a final report.

Run any scenario from the project root, for example:

```bash
uv run python examples/03_stage_retry.py
```

## Concurrent SubStages

A stage can process input items concurrently. Each worker gets a distinct
SubStage instance and follows `setup`, `execute`, then `cleanup`; this is useful
for holding one Selenium browser per worker.

```python
@app.substage()
class FillForm(sm.SubStage):
    def setup(self, context: sm.WorkerContext) -> None:
        self.browser = create_browser()

    def execute(self, context: sm.SubStageContext) -> None:
        fill_form(self.browser, context.item)

    def cleanup(self, context: sm.WorkerContext) -> None:
        self.browser.quit()


@app.stage(concurrency=4)
async def fill_all_forms(context: sm.StageContext) -> None:
    result = await context.amap_substage(FillForm, read_forms())
    context.data["succeeded"] = result.succeeded
    context.data["failed"] = result.failed
```

Each mapping call returns a `SubStageResult`, identified by `substage_id`. Item
failures are retried independently and reported as `SubStageExecutionResult`
entries; they do not fail the parent stage unless the stage chooses to raise.

## Persistence schema

Each run is persisted as `sm_runs`. Its registered stages are materialized as
`sm_stages`, whose retries are stored in `sm_stage_attempts`. Each call to map a
substage is one `sm_substages` record, and its per-item executions and retries
are stored in `sm_substage_attempts`.

When a run finishes, `sm_runs.result_stage_attempt_id` points to the last
completed stage attempt. That attempt contains the terminal stage status,
context snapshots, error details, and timestamps. The reference remains null
when the run has no stage attempts.

Within `core/model`, SQLAlchemy records live in `database/`, while execution
contracts, contexts, specifications, and results live in `execution/`.

When the application starts, it automatically replaces the legacy
`state_machine_runs`, `state_machine_attempts`, and `state_machine_batches`
tables with this schema. This operation permanently deletes the legacy data.

## Context snapshots

The database keeps a JSON snapshot before and after every stage and substage
attempt. Dictionary keys beginning with `_` are excluded recursively from those
snapshots but remain available in memory. This lets a context retain resources
such as a WebDriver without attempting to serialize it:

```python
context.item["_web_driver"] = self.browser
context.item["processed"] = True
```

All remaining context values must be JSON-compatible. Private values are not
recoverable from the database and must be recreated in a later execution.
