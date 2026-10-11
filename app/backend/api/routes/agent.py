from typing import Annotated, Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query

from ...domain.conversations import UserInfo
from ...services.chat import ChatService
from ..deps import get_chat_service, get_current_user

router = APIRouter(tags=['agent'])


@router.get('/skills')
async def list_skills(service: Annotated[ChatService, Depends(get_chat_service)],
                      user: Annotated[UserInfo, Depends(get_current_user)]) -> dict[str, Any]:
    return {'skills': service.skills.catalog() if service.policy.enabled else [],
            'tools': service.tools.definitions() if service.policy.enabled else []}


@router.get('/agent/tasks')
async def list_tasks(service: Annotated[ChatService, Depends(get_chat_service)],
                     user: Annotated[UserInfo, Depends(get_current_user)], conversation_id: UUID | None = None,
                     offset: Annotated[int, Query(ge=0, le=100000)] = 0,
                     limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, Any]:
    rows = await anyio.to_thread.run_sync(service.tasks.list_tasks, int(user.user_id),
        str(conversation_id) if conversation_id else None, offset, limit)
    return {'tasks': rows, 'offset': offset, 'limit': limit}


@router.get('/agent/tasks/{task_id}')
async def task_detail(task_id: UUID, service: Annotated[ChatService, Depends(get_chat_service)],
                      user: Annotated[UserInfo, Depends(get_current_user)],
                      offset: Annotated[int, Query(ge=0, le=100000)] = 0,
                      limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict[str, Any]:
    return await anyio.to_thread.run_sync(service.tasks.detail, int(user.user_id), str(task_id), offset, limit)
