from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=255)]
