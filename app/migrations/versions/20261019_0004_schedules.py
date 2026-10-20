"""Persistent schedules and execution queue. Apply manually."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '20261019_0004'
down_revision = '20261011_0003'
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(6)')),
            sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'))]


def upgrade():
    op.create_table('scheduled_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('name', sa.String(80), nullable=False), sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False), sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('cron', sa.String(120), nullable=True), sa.Column('run_at', mysql.DATETIME(fsp=6), nullable=True),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('next_run_at', mysql.DATETIME(fsp=6), nullable=True),
        *timestamps(), sa.UniqueConstraint('user_id', 'request_id', name='uq_scheduled_tasks_request'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')
    op.create_index('ix_scheduled_tasks_due', 'scheduled_tasks', ['status', 'next_run_at'])
    op.create_index('ix_scheduled_tasks_owner', 'scheduled_tasks', ['user_id', 'conversation_id', 'created_at'])
    op.create_table('scheduled_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('scheduled_tasks.id'), nullable=False),
        sa.Column('request_id', sa.String(36), nullable=False), sa.Column('source', sa.String(16), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('scheduled_at', mysql.DATETIME(fsp=6), nullable=False),
        sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=True), sa.Column('finished_at', mysql.DATETIME(fsp=6), nullable=True),
        sa.Column('user_message_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('messages.id'), nullable=True),
        sa.Column('assistant_message_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('messages.id'), nullable=True),
        sa.Column('error', sa.String(255), nullable=True), *timestamps(),
        sa.UniqueConstraint('task_id', 'request_id', name='uq_scheduled_runs_request'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')
    op.create_index('ix_scheduled_runs_task', 'scheduled_runs', ['task_id', 'created_at'])
    op.create_index('ix_scheduled_runs_queue', 'scheduled_runs', ['status', 'created_at'])


def downgrade():
    op.drop_table('scheduled_runs')
    op.drop_table('scheduled_tasks')
