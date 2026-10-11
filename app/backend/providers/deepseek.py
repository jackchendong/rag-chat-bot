import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator

import httpx
from pydantic import BaseModel

from ..core.config import Settings
from ..domain.chat import ModelChunk, ModelGateway, ModelMessage
from ..domain.errors import ModelServiceError

logger = logging.getLogger(__name__)


class Delta(BaseModel):
    content: str | None = None


class Choice(BaseModel):
    delta: Delta
    finish_reason: str | None = None


class CompletionChunk(BaseModel):
    choices: list[Choice]


async def upstream_events(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    size = 0
    async for line in response.aiter_lines():
        if line == '':
            if data_lines:
                yield '\n'.join(data_lines)
                data_lines.clear()
                size = 0
        elif line.startswith('data:'):
            value = line[5:].removeprefix(' ')
            size += len(value)
            if size > 1024 * 1024:
                raise ValueError('Upstream event is too large')
            data_lines.append(value)
    if data_lines:
        raise ValueError('Incomplete upstream event')


class DeepSeekClient(ModelGateway):
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    async def stream_answer(self, messages: list[ModelMessage]) -> AsyncGenerator[ModelChunk, None]:
        payload = {
            'model': self.settings.model,
            'messages': [{'role': message.role, 'content': message.content} for message in messages],
            'stream': True,
            'max_tokens': 1024,
            'thinking': {'type': 'disabled'},
        }
        logger.info('%s', json.dumps(payload, ensure_ascii=False))
        try:
            async with self.client.stream(
                'POST',
                f'{self.settings.base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {self.settings.api_key.get_secret_value()}',
                    'Accept': 'text/event-stream',
                },
                json=payload,
            ) as response:
                if response.status_code != 200:
                    code = 'upstream_rate_limit' if response.status_code == 429 else 'upstream_error'
                    raise ModelServiceError(code, '模型服务请求失败，请检查配置或稍后重试')
                if 'text/event-stream' not in response.headers.get('content-type', '').lower():
                    raise ModelServiceError('invalid_stream', '模型服务未返回 SSE 响应')
                finish_reason: str | None = None
                async for payload in upstream_events(response):
                    if payload == '[DONE]':
                        yield ModelChunk(finish_reason=finish_reason, done=True)
                        return
                    chunk = CompletionChunk.model_validate_json(payload)
                    if chunk.choices:
                        choice = chunk.choices[0]
                        if choice.delta.content:
                            yield ModelChunk(content=choice.delta.content)
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
                raise ModelServiceError('incomplete_stream', '模型回答意外中断，请重试')
        except httpx.TimeoutException:
            raise ModelServiceError('upstream_timeout', '模型服务响应超时，请稍后重试') from None
        except httpx.HTTPError:
            raise ModelServiceError('upstream_unavailable', '暂时无法连接模型服务') from None
        except ValueError:
            raise ModelServiceError('invalid_stream', '模型服务返回了无效的流数据') from None
