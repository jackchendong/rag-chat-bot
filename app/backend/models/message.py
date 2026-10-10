from datetime import datetime
from typing import Literal

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base
from ..domain.conversations import MessageStatus


class Message(Base):
    __tablename__ = 'messages'
    __table_args__ = (
        Index('ix_messages_conversation_id', 'conversation_id', 'id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey('conversations.id'), nullable=False)
    role: Mapped[Literal['user', 'assistant']] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, server_default=text('CURRENT_TIMESTAMP(6)'))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False,
        server_default=text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'),
    )
