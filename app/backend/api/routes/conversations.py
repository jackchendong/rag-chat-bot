from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...domain.conversations import ConversationInfo, ConversationStore, MessageInfo, UserInfo
from ...schemas.login import LoginRequest
from ..deps import get_current_user, get_store

router = APIRouter()
CurrentUser = Annotated[UserInfo, Depends(get_current_user)]
Store = Annotated[ConversationStore, Depends(get_store)]


@router.post('/login', response_model=UserInfo)
def login(body: LoginRequest, store: Store) -> UserInfo:
    return store.login(body.account)


@router.get('/users/me', response_model=UserInfo)
def current_user(user: CurrentUser) -> UserInfo:
    return user


@router.post('/conversations', response_model=ConversationInfo, status_code=201)
def create_conversation(user: CurrentUser, store: Store) -> ConversationInfo:
    return store.create_conversation(int(user.user_id))


@router.get('/conversations', response_model=list[ConversationInfo])
def list_conversations(
    user: CurrentUser, store: Store,
    offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[ConversationInfo]:
    return store.list_conversations(int(user.user_id), offset, limit)


@router.get('/conversations/{conversation_id}/messages', response_model=list[MessageInfo])
def list_messages(
    conversation_id: UUID, user: CurrentUser, store: Store,
    before: Annotated[int | None, Query(ge=1, le=18446744073709551615)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MessageInfo]:
    return store.list_messages(int(user.user_id), str(conversation_id), before, limit)
