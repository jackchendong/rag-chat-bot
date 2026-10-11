from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ModelChunk:
    content: str | None = None
    finish_reason: str | None = None
    done: bool = False


@dataclass(frozen=True)
class ChatEvent:
    event: Literal['meta', 'message', 'done', 'error']
    data: dict[str, object]


@dataclass(frozen=True)
class ModelMessage:
    role: Literal['user', 'assistant']
    content: str


class ModelGateway(ABC):
    @abstractmethod
    def stream_answer(self, messages: list[ModelMessage]) -> AsyncGenerator[ModelChunk, None]:
        raise NotImplementedError
