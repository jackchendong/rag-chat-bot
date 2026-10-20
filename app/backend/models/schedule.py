from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from .agent import AuditTimestamps


class ScheduledTask(AuditTimestamps, Base):
    __tablename__ = 'scheduled_tasks'
    __table_args__ = (
        Index('ix_scheduled_tasks_due', 'status', 'next_run_at'),
        Index('ix_scheduled_tasks_owner', 'user_id', 'conversation_id', 'created_at'),
        UniqueConstraint('user_id', 'request_id', name='uq_scheduled_tasks_request'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey('conversations.id'))
    request_id: Mapped[str] = mapped_column(String(36))
    name: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64))
    cron: Mapped[str | None] = mapped_column(String(120))
    run_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    status: Mapped[str] = mapped_column(String(16))
    next_run_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))


class ScheduledRun(AuditTimestamps, Base):
    __tablename__ = 'scheduled_runs'
    __table_args__ = (
        Index('ix_scheduled_runs_task', 'task_id', 'created_at'),
        Index('ix_scheduled_runs_queue', 'status', 'created_at'),
        UniqueConstraint('task_id', 'request_id', name='uq_scheduled_runs_request'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey('scheduled_tasks.id'))
    request_id: Mapped[str] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(16))
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    scheduled_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    started_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    user_message_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), ForeignKey('messages.id'))
    assistant_message_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), ForeignKey('messages.id'))
    error: Mapped[str | None] = mapped_column(String(255))
