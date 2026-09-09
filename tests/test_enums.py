from typing import cast

import pytest

from state_machine.core.domain.enums import RunStatus

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
