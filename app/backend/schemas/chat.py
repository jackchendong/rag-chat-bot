from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_id: UUID
    message: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=10000)
    ]
    skill_names: list[Annotated[str, StringConstraints(strict=True, pattern=r'^[a-z0-9][a-z0-9-]{0,63}$')]] = Field(default_factory=list, max_length=8)


class ChatStopRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_id: UUID
    assistant_message_id: Annotated[
        str, StringConstraints(strict=True, pattern=r'^[1-9][0-9]{0,19}$')
    ]

    @field_validator('assistant_message_id')
    @classmethod
    def validate_message_id(cls, value: str) -> str:
        if int(value) > 18446744073709551615:
            raise ValueError('回答 ID 超出范围')
        return value


class ChatStopResponse(BaseModel):
    stopped: bool
