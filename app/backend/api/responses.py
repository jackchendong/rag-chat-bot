import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import aclosing

import anyio
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ..domain.chat import ChatEvent


async def encode_events(events: AsyncGenerator[ChatEvent, None]) -> AsyncGenerator[str, None]:
    async with aclosing(events):
        async for event in events:
            yield f'event: {event.event}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n'


class SSEStreamingResponse(StreamingResponse):
    def __init__(self, events: AsyncGenerator[ChatEvent, None], on_close: Callable[[], Awaitable[None]]) -> None:
        self.answer = encode_events(events)
        self.on_close = on_close
        super().__init__(
            self.answer,
            media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.answer.aclose()
                await self.on_close()
