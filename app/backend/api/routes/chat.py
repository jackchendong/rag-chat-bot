from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from ...schemas.chat import ChatRequest
from ...services.chat import ChatService
from ..deps import get_chat_service
from ..responses import SSEStreamingResponse


router = APIRouter()


@router.post('/chat', response_class=StreamingResponse, responses={
    200: {'content': {'text/event-stream': {}}, 'description': '流式回答或模型服务错误事件'},
})
async def chat(
    body: ChatRequest, service: Annotated[ChatService, Depends(get_chat_service)]
) -> StreamingResponse:
    return SSEStreamingResponse(service.answer(body.message))
