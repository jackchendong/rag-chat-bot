"""Create the users table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision: str = '20261010_0001'
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False),
        sa.Column('account', sa.String(length=255), nullable=False),
        sa.Column(
            'created_at', mysql.DATETIME(fsp=6),
            server_default=sa.text('CURRENT_TIMESTAMP(6)'), nullable=False,
        ),
        sa.Column(
            'updated_at', mysql.DATETIME(fsp=6),
            server_default=sa.text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci',
    )


def downgrade() -> None:
    op.drop_table('users')
