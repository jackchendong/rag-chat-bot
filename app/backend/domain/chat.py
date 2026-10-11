from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def as_dict(self) -> dict[str, object]:
        return {'id': self.id, 'type': 'function', 'function': {'name': self.name, 'arguments': self.arguments}}


@dataclass(frozen=True)
class ModelChunk:
    content: str | None = None
    finish_reason: str | None = None
    done: bool = False
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class ChatEvent:
    event: Literal['meta', 'message', 'done', 'error', 'agent_step']
    data: dict[str, object]


@dataclass(frozen=True)
class ModelMessage:
    role: Literal['system', 'user', 'assistant', 'tool']
    content: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {'role': self.role, 'content': self.content}
        if self.tool_calls:
            result['tool_calls'] = [call.as_dict() for call in self.tool_calls]
        if self.tool_call_id:
            result['tool_call_id'] = self.tool_call_id
        return result


class ModelGateway(ABC):
    @abstractmethod
    def stream_answer(self, messages: list[ModelMessage], tools: list[dict[str, object]] | None = None) -> AsyncGenerator[ModelChunk, None]:
        raise NotImplementedError
