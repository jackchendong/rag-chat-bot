from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import Mapped, mapped_column

from ..db.base import Base


class Conversation(Base):
    __tablename__ = 'conversations'
    __table_args__ = (
        Index('ix_conversations_user_updated', 'user_id', 'updated_at'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4', 'mysql_collate': 'utf8mb4_unicode_ci'},
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), ForeignKey('users.id'), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    active_message_id: Mapped[int | None] = mapped_column(BIGINT(unsigned=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), nullable=False, server_default=text('CURRENT_TIMESTAMP(6)'))
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=6), nullable=False,
        server_default=text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'),
    )
