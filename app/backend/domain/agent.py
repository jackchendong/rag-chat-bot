from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .conversations import PreparedTurn


@dataclass(frozen=True)
class AgentPolicy:
    enabled: bool = True
    max_rounds: int = 6
    max_tool_calls: int = 12
    timeout_seconds: float = 120
    tool_timeout_seconds: float = 20
    stop_poll_seconds: float = 0.25
    max_tool_output_chars: int = 12000


@dataclass(frozen=True)
class ToolContext:
    user_id: int
    conversation_id: str
    user_message_id: str = ''
    scheduled_execution: bool = False


@dataclass(frozen=True)
class PreparedRun:
    turn: PreparedTurn
    task_id: str
    system_prompt: str
    tool_context: ToolContext | None = None


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Tool(ABC):
    def bind(self, context: ToolContext) -> 'Tool | None':
        return self

    @property
    @abstractmethod
    def definition(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class SkillSource(ABC):
    @abstractmethod
    def catalog(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @abstractmethod
    def load(self, name: str) -> dict[str, str]:
        raise NotImplementedError


class ToolExecutor(ABC):
    def bind(self, context: ToolContext) -> 'ToolExecutor':
        return self

    @abstractmethod
    def definitions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, name: str, arguments: str) -> dict[str, Any]:
        raise NotImplementedError


class AgentTaskStore(ABC):
    @abstractmethod
    def start(self, turn: PreparedTurn, model: str, settings: dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    def begin_step(self, task_id: str, round_no: int, kind: str, name: str,
                   input_data: dict[str, Any], tool_call_id: str | None = None) -> int:
        raise NotImplementedError

    @abstractmethod
    def end_step(self, step_id: int, status: str, output: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def finish(self, task_id: str, status: str, output: str, error: dict[str, str] | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_tasks(self, user_id: int, conversation_id: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def detail(self, user_id: int, task_id: str, offset: int, limit: int) -> dict[str, Any]:
        raise NotImplementedError
