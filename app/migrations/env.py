from alembic import context

from backend.core.config import DatabaseSettings
from backend.db.session import create_database_engine
from backend.models import User

target_metadata = User.metadata


def run_migrations_offline() -> None:
    context.configure(
        dialect_name='mysql',
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_database_engine(DatabaseSettings.load())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
