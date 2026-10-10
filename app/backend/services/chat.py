import logging
import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing

import anyio

from ..domain.chat import ChatEvent, ModelGateway
from ..domain.conversations import ConversationStore, MessageStatus, PreparedTurn
from ..domain.errors import ConversationError, ModelServiceError

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, gateway: ModelGateway, store: ConversationStore) -> None:
        self.gateway = gateway
        self.store = store

    async def prepare(self, user_id: int, conversation_id: str, message: str) -> PreparedTurn:
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(self.store.prepare_turn, user_id, conversation_id, message)

    async def save(self, turn: PreparedTurn, content: str, status: MessageStatus) -> None:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(self.store.finish_turn, turn, content, status)

    async def cancel(self, turn: PreparedTurn) -> None:
        try:
            await self.save(turn, '', 'cancelled')
        except ConversationError:
            logger.warning('Could not finalize an abandoned chat response')

    async def answer(self, turn: PreparedTurn) -> AsyncGenerator[ChatEvent, None]:
        content = ''
        persisted = False
        try:
            yield ChatEvent('meta', {
                'conversation_id': turn.conversation_id,
                'user_message_id': turn.user_message_id,
                'assistant_message_id': turn.assistant_message_id,
            })
            deadline = time.monotonic() + 120
            async with aclosing(self.gateway.stream_answer(turn.messages)) as chunks:
                while True:
                    try:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError
                        chunk = await asyncio.wait_for(anext(chunks), timeout=remaining)
                    except StopAsyncIteration:
                        raise ModelServiceError('incomplete_stream', '模型回答意外中断，请重试') from None
                    if chunk.content:
                        if len((content + chunk.content).encode('utf-8')) > 60000:
                            raise ModelServiceError('output_limit', '回答超过长度限制，请缩小问题范围')
                        content += chunk.content
                        yield ChatEvent('message', {'content': chunk.content})
                    if chunk.done:
                        await self.save(turn, content, 'completed')
                        persisted = True
                        yield ChatEvent('done', {
                            'finish_reason': chunk.finish_reason,
                            'truncated': chunk.finish_reason == 'length',
                        })
                        return
        except (ModelServiceError, ConversationError, asyncio.TimeoutError, TimeoutError) as error:
            if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
                error = ModelServiceError('upstream_timeout', '回答生成超时，请稍后重试')
            try:
                await self.save(turn, content, 'failed')
                persisted = True
            except ConversationError as storage_error:
                error = storage_error
            yield ChatEvent('error', {'code': error.code, 'message': error.message})
        finally:
            if not persisted:
                try:
                    await self.save(turn, content, 'cancelled')
                except ConversationError:
                    logger.warning('Could not persist a cancelled chat response')
