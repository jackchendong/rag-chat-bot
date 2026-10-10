"""Add account uniqueness and conversation history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '20261010_0002'
down_revision: str | None = '20261010_0001'
branch_labels: str | None = None
depends_on: str | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(6)')),
        sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)')),
    ]


def upgrade() -> None:
    op.create_unique_constraint('uq_users_account', 'users', ['account'])
    op.create_table(
        'conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(80), nullable=False),
        sa.Column('active_message_id', mysql.BIGINT(unsigned=True), nullable=True),
        *timestamps(),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci',
    )
    op.create_index('ix_conversations_user_updated', 'conversations', ['user_id', 'updated_at'])
    op.create_table(
        'messages',
        sa.Column('id', mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        *timestamps(),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci',
    )
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id', 'id'])


def downgrade() -> None:
    op.drop_table('messages')
    op.drop_table('conversations')
    op.drop_constraint('uq_users_account', 'users', type_='unique')
