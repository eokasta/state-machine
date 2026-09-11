# ruff: noqa: TC003

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from state_machine.core.model.database.base import Base


class RunRecord(Base):
    __tablename__ = "sm_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    result_stage_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "sm_stage_attempts.id",
            name="fk_sm_runs_result_stage_attempt_id",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
