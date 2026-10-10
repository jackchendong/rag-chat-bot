from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings) -> Engine:
    return create_engine(
        settings.url,
        pool_pre_ping=True,
        pool_recycle=1800,
        hide_parameters=True,
        connect_args={
            'connect_timeout': 10,
            'read_timeout': 10,
            'write_timeout': 10,
            'init_command': "SET time_zone = '+00:00'",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
