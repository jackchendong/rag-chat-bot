from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    conversation_id: UUID
    message: Annotated[
        str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=10000)
    ]
