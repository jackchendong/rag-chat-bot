from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...schemas.chat import ChatRequest
from ...services.chat import ChatService
from ...domain.conversations import UserInfo
from ..deps import get_chat_service, get_current_user
from ..responses import SSEStreamingResponse


router = APIRouter()


@router.post('/chat', response_class=StreamingResponse, responses={
    200: {'content': {'text/event-stream': {}}, 'description': '流式回答或模型服务错误事件'},
})
async def chat(
    body: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)],
    user: Annotated[UserInfo, Depends(get_current_user)],
) -> StreamingResponse:
    turn = await service.prepare(int(user.user_id), str(body.conversation_id), body.message)
    return SSEStreamingResponse(service.answer(turn), lambda: service.cancel(turn))
