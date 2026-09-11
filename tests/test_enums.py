from typing import cast

import pytest

from state_machine.core.domain.enums import (
    AttemptStatus,
    RunStatus,
    StageStatus,
    SubStageStatus,
)

TRANSITIONS = [
    (current, next_status, next_status in current_targets)
    for current, current_targets in {
        RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.RUNNING: {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.RETRY_PENDING,
            RunStatus.CANCELLED,
        },
        RunStatus.RETRY_PENDING: {
            RunStatus.RUNNING,
            RunStatus.DEAD_LETTER,
            RunStatus.CANCELLED,
        },
        RunStatus.FAILED: {RunStatus.RETRY_PENDING, RunStatus.DEAD_LETTER},
        RunStatus.SUCCEEDED: set(),
        RunStatus.CANCELLED: set(),
        RunStatus.DEAD_LETTER: set(),
    }.items()
    for next_status in RunStatus
]


@pytest.mark.parametrize(("current", "next_status", "expected"), TRANSITIONS)
def test_can_transition_to_all_status_combinations(
    current: RunStatus, next_status: RunStatus, expected: bool
) -> None:
    assert current.can_transition_to(next_status) is expected


@pytest.mark.parametrize("incompatible_status", ["RUNNING", None, object()])
def test_cannot_transition_to_incompatible_status(
    incompatible_status: object,
) -> None:
    status = cast("RunStatus", incompatible_status)

    assert RunStatus.PENDING.can_transition_to(status) is False


ATTEMPT_TRANSITIONS = [
    (current, next_status, next_status != current and current is AttemptStatus.RUNNING)
    for current in AttemptStatus
    for next_status in AttemptStatus
]


@pytest.mark.parametrize(("current", "next_status", "expected"), ATTEMPT_TRANSITIONS)
def test_attempt_status_can_transition_to_all_status_combinations(
    current: AttemptStatus, next_status: AttemptStatus, expected: bool
) -> None:
    assert current.can_transition_to(next_status) is expected


@pytest.mark.parametrize("incompatible_status", ["SUCCEEDED", None, object()])
def test_attempt_status_cannot_transition_to_incompatible_status(
    incompatible_status: object,
) -> None:
    status = cast("AttemptStatus", incompatible_status)

    assert AttemptStatus.RUNNING.can_transition_to(status) is False


STAGE_LIFECYCLE_TRANSITIONS = [
    (current, next_status, next_status in current_targets)
    for status, targets in {
        StageStatus: {
            StageStatus.PENDING: {StageStatus.RUNNING, StageStatus.CANCELLED},
            StageStatus.RUNNING: {
                StageStatus.SUCCEEDED,
                StageStatus.FAILED,
                StageStatus.CANCELLED,
            },
            StageStatus.SUCCEEDED: set(),
            StageStatus.FAILED: set(),
            StageStatus.CANCELLED: set(),
        },
        SubStageStatus: {
            SubStageStatus.PENDING: {
                SubStageStatus.RUNNING,
                SubStageStatus.CANCELLED,
            },
            SubStageStatus.RUNNING: {
                SubStageStatus.SUCCEEDED,
                SubStageStatus.FAILED,
                SubStageStatus.CANCELLED,
            },
            SubStageStatus.SUCCEEDED: set(),
            SubStageStatus.FAILED: set(),
            SubStageStatus.CANCELLED: set(),
        },
    }.items()
    for current, current_targets in targets.items()
    for next_status in status
]


@pytest.mark.parametrize(
    ("current", "next_status", "expected"), STAGE_LIFECYCLE_TRANSITIONS
)
def test_stage_and_substage_statuses_cover_all_transitions(
    current: StageStatus | SubStageStatus,
    next_status: StageStatus | SubStageStatus,
    expected: bool,
) -> None:
    assert current.can_transition_to(next_status) is expected


@pytest.mark.parametrize(
    ("current", "next_status"),
    [
        (RunStatus.PENDING, StageStatus.RUNNING),
        (StageStatus.PENDING, SubStageStatus.RUNNING),
        (SubStageStatus.PENDING, AttemptStatus.RUNNING),
        (AttemptStatus.RUNNING, RunStatus.SUCCEEDED),
    ],
)
def test_status_cannot_transition_to_another_status_type(
    current: RunStatus | StageStatus | SubStageStatus | AttemptStatus,
    next_status: RunStatus | StageStatus | SubStageStatus | AttemptStatus,
) -> None:
    assert current.can_transition_to(next_status) is False
