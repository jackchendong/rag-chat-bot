from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .api.routes.chat import router
from .core.config import Settings
from .providers.deepseek import DeepSeekClient
from .services.chat import ChatService


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings.load()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.timeout, connect=10),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    ) as client:
        application.state.chat_service = ChatService(DeepSeekClient(client, settings))
        yield


def create_app() -> FastAPI:
    application = FastAPI(title='大模型对话 Demo', lifespan=lifespan)
    application.include_router(router, prefix='/api')
    return application
