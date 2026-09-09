from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class RunStatus(StrEnum):

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_PENDING = "RETRY_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTER = "DEAD_LETTER"

    def can_transition_to(self, status: RunStatus) -> bool:
        """Return whether transitioning from this status to ``status`` is valid."""
        if not isinstance(status, RunStatus):
            return False
        return status in RUN_STATUS_ALLOWED_TRANSITIONS.get(self, frozenset())


RUN_STATUS_ALLOWED_TRANSITIONS: Final = MappingProxyType(
    {
        RunStatus.PENDING: frozenset(
            {
                RunStatus.RUNNING,
                RunStatus.CANCELLED,
            }
        ),
        RunStatus.RUNNING: frozenset(
            {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.RETRY_PENDING,
                RunStatus.CANCELLED,
            }
        ),
        RunStatus.RETRY_PENDING: frozenset(
            {
                RunStatus.RUNNING,
                RunStatus.DEAD_LETTER,
                RunStatus.CANCELLED,
            }
        ),
        RunStatus.FAILED: frozenset(
            {
                RunStatus.RETRY_PENDING,
                RunStatus.DEAD_LETTER,
            }
        ),
    }
)


class AttemptStatus(StrEnum):

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"

    def can_transition_to(self, status: AttemptStatus) -> bool:
        """Return whether transitioning from this status to ``status`` is valid."""
        if not isinstance(status, AttemptStatus):
            return False

        return self == AttemptStatus.RUNNING and self != status
