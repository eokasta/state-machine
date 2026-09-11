# ruff: noqa: TC001, TC003

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from state_machine.core.model.database.base import Base
from state_machine.core.util.json_value import JsonValue


class SubStageRecord(Base):
    __tablename__ = "sm_substages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stage_attempt_id: Mapped[str] = mapped_column(
        ForeignKey("sm_stage_attempts.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SubStageAttemptRecord(Base):
    __tablename__ = "sm_substage_attempts"
    __table_args__ = (UniqueConstraint("substage_id", "item_index", "attempt_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    substage_id: Mapped[str] = mapped_column(ForeignKey("sm_substages.id"), index=True)
    item_index: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[int] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    context_before: Mapped[JsonValue | None] = mapped_column(JSON, nullable=True)
    context_after: Mapped[JsonValue | None] = mapped_column(JSON, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
