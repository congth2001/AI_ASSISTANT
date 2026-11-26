from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects import postgresql

from src.common.infrastructure.database.base import Base

SYNC_SOURCES = ("mdb", "snapshot")
SYNC_STATUSES = ("running", "succeeded", "failed")
SINGLE_RUNNING_INDEX = "uq_data_sync_jobs_single_running"


class DataSyncJobModel(Base):
    """One sync started from the admin screen (CLI/cron runs are not listed here)."""

    __tablename__ = "data_sync_jobs"

    id = Column(String(36), primary_key=True)
    source = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False)
    allow_shrink = Column(Boolean, nullable=False, server_default=text("false"))
    triggered_by_id = Column(
        String(36),
        ForeignKey("users.id", name="fk_data_sync_jobs_triggered_by_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False)
    heartbeat_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(postgresql.JSONB, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "source IN ('mdb', 'snapshot')", name="ck_data_sync_jobs_source"
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_data_sync_jobs_status"
        ),
        # At most one running job, even when two requests race.
        Index(
            SINGLE_RUNNING_INDEX,
            "status",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_data_sync_jobs_created_at", "created_at"),
        {"comment": "Admin-triggered business-data syncs; at most one running row."},
    )
