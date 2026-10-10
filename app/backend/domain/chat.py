from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class ModelChunk:
    content: str | None = None
    finish_reason: str | None = None
    done: bool = False


@dataclass(frozen=True)
class ChatEvent:
    event: Literal['message', 'done', 'error']
    data: dict[str, object]


class ModelGateway(Protocol):
    def stream_answer(self, message: str) -> AsyncGenerator[ModelChunk, None]:
        ...
