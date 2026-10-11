"""Agent execution audit trail. Explicit offline-safe migration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = '20261011_0003'
down_revision = '20261010_0002'
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column('created_at', mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(6)')),
            sa.Column('updated_at', mysql.DATETIME(fsp=6), nullable=False,
                      server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'))]


def upgrade():
    op.create_table('agent_tasks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('user_message_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('assistant_message_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False), sa.Column('model', sa.String(128), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=False), sa.Column('output_text', sa.Text(), nullable=False),
        sa.Column('settings_snapshot', sa.JSON(), nullable=False),
        sa.Column('round_count', sa.Integer(), nullable=False), sa.Column('tool_call_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.JSON(), nullable=True), sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=False),
        sa.Column('finished_at', mysql.DATETIME(fsp=6), nullable=True), *timestamps(),
        sa.UniqueConstraint('assistant_message_id', name='uq_agent_tasks_assistant_message'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')
    op.create_index('ix_agent_tasks_user_created', 'agent_tasks', ['user_id', 'created_at'])
    op.create_index('ix_agent_tasks_conversation_created', 'agent_tasks', ['conversation_id', 'created_at'])
    op.create_table('agent_task_steps',
        sa.Column('id', mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('agent_tasks.id'), nullable=False),
        sa.Column('step_no', sa.Integer(), nullable=False), sa.Column('round_no', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(16), nullable=False), sa.Column('name', sa.String(128), nullable=False),
        sa.Column('tool_call_id', sa.String(128), nullable=True), sa.Column('status', sa.String(16), nullable=False),
        sa.Column('input_data', sa.JSON(), nullable=False), sa.Column('output_data', sa.JSON(), nullable=True),
        sa.Column('started_at', mysql.DATETIME(fsp=6), nullable=False),
        sa.Column('finished_at', mysql.DATETIME(fsp=6), nullable=True), sa.Column('duration_ms', sa.Integer(), nullable=True),
        *timestamps(), sa.UniqueConstraint('task_id', 'step_no', name='uq_agent_steps_sequence'),
        sa.UniqueConstraint('task_id', 'tool_call_id', name='uq_agent_steps_tool_call'),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')


def downgrade():
    op.drop_table('agent_task_steps')
    op.drop_table('agent_tasks')
