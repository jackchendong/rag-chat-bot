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

    async def save(self, turn: PreparedTurn, content: str, status: MessageStatus) -> MessageStatus:
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(self.store.finish_turn, turn, content, status)

    async def stop(self, user_id: int, conversation_id: str, assistant_message_id: int) -> bool:
        with anyio.CancelScope(shield=True):
            return await anyio.to_thread.run_sync(
                self.store.stop_turn, user_id, conversation_id, assistant_message_id,
            )

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
            next_stop_check = 0.0
            stopped = False
            finish_reason: str | None = None
            async with aclosing(self.gateway.stream_answer(turn.messages)) as chunks:
                while True:
                    pending_chunk = asyncio.create_task(anext(chunks))
                    try:
                        while True:
                            if time.monotonic() >= next_stop_check:
                                stopped = await anyio.to_thread.run_sync(self.store.is_turn_cancelled, turn)
                                next_stop_check = time.monotonic() + 0.25
                                if stopped:
                                    break
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                raise TimeoutError
                            done, _ = await asyncio.wait(
                                {pending_chunk}, timeout=min(remaining, max(0, next_stop_check - time.monotonic())),
                            )
                            if done:
                                break
                        if stopped:
                            break
                        chunk = pending_chunk.result()
                    except StopAsyncIteration:
                        raise ModelServiceError('incomplete_stream', '模型回答意外中断，请重试') from None
                    finally:
                        if not pending_chunk.done():
                            pending_chunk.cancel()
                        with anyio.CancelScope(shield=True):
                            await asyncio.gather(pending_chunk, return_exceptions=True)
                    if chunk.content:
                        if len((content + chunk.content).encode('utf-8')) > 60000:
                            raise ModelServiceError('output_limit', '回答超过长度限制，请缩小问题范围')
                        content += chunk.content
                        yield ChatEvent('message', {'content': chunk.content})
                    if chunk.done:
                        finish_reason = chunk.finish_reason
                        break
            status = await self.save(turn, content, 'cancelled' if stopped else 'completed')
            persisted = True
            yield ChatEvent('done', {
                'finish_reason': 'cancelled' if status == 'cancelled' else finish_reason,
                'truncated': status != 'cancelled' and finish_reason == 'length',
                'cancelled': status == 'cancelled',
            })
        except (ModelServiceError, ConversationError, asyncio.TimeoutError, TimeoutError) as error:
            if isinstance(error, (asyncio.TimeoutError, TimeoutError)):
                error = ModelServiceError('upstream_timeout', '回答生成超时，请稍后重试')
            try:
                status = await self.save(turn, content, 'failed')
                persisted = True
                if status == 'cancelled':
                    yield ChatEvent('done', {'finish_reason': 'cancelled', 'truncated': False, 'cancelled': True})
                    return
            except ConversationError as storage_error:
                error = storage_error
            yield ChatEvent('error', {'code': error.code, 'message': error.message})
        finally:
            if not persisted:
                try:
                    await self.save(turn, content, 'cancelled')
                except ConversationError:
                    logger.warning('Could not persist a cancelled chat response')
