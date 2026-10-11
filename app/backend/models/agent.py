from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class AuditTimestamps:
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, server_default=text('CURRENT_TIMESTAMP(6)'))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False,
        server_default=text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'))


class AgentTask(AuditTimestamps, Base):
    __tablename__ = 'agent_tasks'
    __table_args__ = (
        Index('ix_agent_tasks_user_created', 'user_id', 'created_at'),
        Index('ix_agent_tasks_conversation_created', 'conversation_id', 'created_at'),
        UniqueConstraint('assistant_message_id', name='uq_agent_tasks_assistant_message'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey('conversations.id'), nullable=False)
    user_message_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('messages.id'), nullable=False)
    assistant_message_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('messages.id'), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)
    settings_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    round_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)


class AgentTaskStep(AuditTimestamps, Base):
    __tablename__ = 'agent_task_steps'
    __table_args__ = (
        UniqueConstraint('task_id', 'step_no', name='uq_agent_steps_sequence'),
        UniqueConstraint('task_id', 'tool_call_id', name='uq_agent_steps_tool_call'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey('agent_tasks.id'), nullable=False)
    step_no: Mapped[int] = mapped_column(Integer, nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
