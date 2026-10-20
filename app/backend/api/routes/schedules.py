from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from ...domain.conversations import UserInfo
from ...repositories.schedules import ScheduleRepository
from ...schemas.schedule import CreateSchedule, RunNow, ScheduleInput, ScheduleState
from ..deps import get_current_user

router = APIRouter(prefix='/scheduled-tasks', tags=['scheduled-tasks'])
CurrentUser = Annotated[UserInfo, Depends(get_current_user)]


def get_schedules(request: Request) -> ScheduleRepository:
    return request.app.state.schedule_store


Store = Annotated[ScheduleRepository, Depends(get_schedules)]
Offset = Annotated[int, Query(ge=0, le=100000)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get('')
def list_tasks(user: CurrentUser, store: Store, conversation_id: UUID | None = None,
               offset: Offset = 0, limit: Limit = 30) -> list[dict[str, Any]]:
    return store.list_tasks(int(user.user_id), str(conversation_id) if conversation_id else None, offset, limit)


@router.post('', status_code=201)
def create_task(body: CreateSchedule, user: CurrentUser, store: Store) -> dict[str, Any]:
    return store.save(int(user.user_id), body.model_dump())


@router.post('/{task_id}/edit')
def edit_task(task_id: UUID, body: ScheduleInput, user: CurrentUser, store: Store) -> dict[str, Any]:
    return store.save(int(user.user_id), body.model_dump(), str(task_id))


@router.post('/{task_id}/state')
def set_state(task_id: UUID, body: ScheduleState, user: CurrentUser, store: Store) -> dict[str, Any]:
    return store.set_state(int(user.user_id), str(task_id), body.status)


@router.post('/{task_id}/run', status_code=202)
def run_now(task_id: UUID, body: RunNow, user: CurrentUser, store: Store) -> dict[str, Any]:
    return store.enqueue(int(user.user_id), str(task_id), str(body.request_id))


@router.get('/{task_id}/runs')
def list_runs(task_id: UUID, user: CurrentUser, store: Store,
              offset: Offset = 0, limit: Limit = 20) -> list[dict[str, Any]]:
    return store.runs(int(user.user_id), str(task_id), offset, limit)
