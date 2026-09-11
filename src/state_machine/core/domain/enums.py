"""Fixed lifecycle states used by the execution model."""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class _TransitionStatus(StrEnum):
    def can_transition_to(self, status: StrEnum) -> bool:
        if not isinstance(status, type(self)):
            return False
        return status in _ALLOWED_TRANSITIONS.get((type(self), self), frozenset())


class RunStatus(_TransitionStatus):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_PENDING = "RETRY_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"


class StageStatus(_TransitionStatus):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SubStageStatus(_TransitionStatus):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AttemptStatus(_TransitionStatus):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


_ALLOWED_TRANSITIONS: Final = MappingProxyType(
    {
        (RunStatus, RunStatus.PENDING): frozenset(
            {RunStatus.RUNNING, RunStatus.CANCELLED}
        ),
        (RunStatus, RunStatus.RUNNING): frozenset(
            {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.RETRY_PENDING,
                RunStatus.CANCELLED,
            }
        ),
        (RunStatus, RunStatus.RETRY_PENDING): frozenset(
            {RunStatus.RUNNING, RunStatus.DEAD_LETTER, RunStatus.CANCELLED}
        ),
        (RunStatus, RunStatus.FAILED): frozenset(
            {RunStatus.RETRY_PENDING, RunStatus.DEAD_LETTER}
        ),
        (StageStatus, StageStatus.PENDING): frozenset(
            {StageStatus.RUNNING, StageStatus.CANCELLED}
        ),
        (StageStatus, StageStatus.RUNNING): frozenset(
            {StageStatus.SUCCEEDED, StageStatus.FAILED, StageStatus.CANCELLED}
        ),
        (SubStageStatus, SubStageStatus.PENDING): frozenset(
            {SubStageStatus.RUNNING, SubStageStatus.CANCELLED}
        ),
        (SubStageStatus, SubStageStatus.RUNNING): frozenset(
            {
                SubStageStatus.SUCCEEDED,
                SubStageStatus.FAILED,
                SubStageStatus.CANCELLED,
            }
        ),
        (AttemptStatus, AttemptStatus.RUNNING): frozenset(
            {
                AttemptStatus.SUCCEEDED,
                AttemptStatus.FAILED,
                AttemptStatus.ABANDONED,
            }
        ),
    }
)
