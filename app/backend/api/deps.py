from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..services.chat import ChatService
from ..domain.conversations import ConversationStore, UserInfo
from ..domain.errors import ConversationError


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_store(request: Request) -> ConversationStore:
    return request.app.state.conversation_store


def get_current_user(
    store: Annotated[ConversationStore, Depends(get_store)],
    user_id: Annotated[str | None, Header(alias='X-User-Id')] = None,
) -> UserInfo:
    if user_id is None or not user_id.isascii() or not user_id.isdecimal() or len(user_id) > 20:
        raise ConversationError('invalid_user', '请先登录并提供有效的 X-User-Id')
    identifier = int(user_id)
    if not 1 <= identifier <= 18446744073709551615:
        raise ConversationError('invalid_user', '用户 ID 无效，请重新登录')
    return store.get_user(identifier)


def get_db_session(request: Request) -> Generator[Session, None, None]:
    with request.app.state.session_factory() as session:
        yield session
