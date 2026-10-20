from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ScheduledExecution:
    run_id: str
    user_id: int
    conversation_id: str
    prompt: str


class ScheduleStore(Protocol):
    def claim(self) -> ScheduledExecution | None: ...
    def recover(self) -> None: ...
    def finish(self, run_id: str, status: str, error: str | None) -> None: ...


class ScheduleCreator(Protocol):
    def save(self, user_id: int, data: dict[str, Any], task_id: str | None = None) -> dict[str, Any]: ...
