import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import PlainTextResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.service.chat_service import chat_with_openai, stream_chat_with_openai
from app.service.user_service import (
    create_user as create_user_service,
    delete_user as delete_user_service,
    get_user as get_user_service,
    list_users as list_users_service,
    update_user as update_user_service,
)

router = APIRouter()


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    username: str
    email: str | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None


class ChatRequest(BaseModel):
    message: str
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    answer: str


@router.get("/", response_class=PlainTextResponse)
def healthcheck() -> str:
    return "ok"


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    try:
        answer = chat_with_openai(payload.message, payload.system_prompt)
        return ChatResponse(answer=answer)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"chat failed: {exc}",
        ) from exc


@router.post("/chat/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    def event_generator():
        try:
            for chunk in stream_chat_with_openai(payload.message, payload.system_prompt):
                yield f"data: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/users", response_model=list[UserOut])
def list_users(
    q: str | None = None,
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[UserOut]:
    return list_users_service(db, q=q, limit=limit, offset=offset)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user_detail(user_id: int, db: Session = Depends(get_db)) -> UserOut:
    user = get_user_service(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user_item(payload: UserCreate, db: Session = Depends(get_db)) -> UserOut:
    try:
        return create_user_service(db, username=payload.username, email=payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/users/{user_id}", response_model=UserOut)
def update_user_item(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
) -> UserOut:
    try:
        user = update_user_service(db, user_id, username=payload.username, email=payload.email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_item(user_id: int, db: Session = Depends(get_db)) -> Response:
    deleted = delete_user_service(db, user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
