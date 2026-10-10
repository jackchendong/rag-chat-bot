from collections.abc import AsyncGenerator
from contextlib import aclosing

from ..domain.chat import ChatEvent, ModelGateway
from ..domain.errors import ModelServiceError


class ChatService:
    def __init__(self, gateway: ModelGateway) -> None:
        self.gateway = gateway

    async def answer(self, message: str) -> AsyncGenerator[ChatEvent, None]:
        try:
            async with aclosing(self.gateway.stream_answer(message)) as chunks:
                async for chunk in chunks:
                    if chunk.content:
                        yield ChatEvent('message', {'content': chunk.content})
                    if chunk.done:
                        yield ChatEvent('done', {
                            'finish_reason': chunk.finish_reason,
                            'truncated': chunk.finish_reason == 'length',
                        })
                        return
            raise ModelServiceError('incomplete_stream', '模型回答意外中断，请重试')
        except ModelServiceError as error:
            yield ChatEvent('error', {'code': error.code, 'message': error.message})
