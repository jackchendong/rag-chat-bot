from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from ..services.chat import ChatService


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_db_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
