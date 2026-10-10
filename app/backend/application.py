from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .api.routes.chat import router
from .core.config import DatabaseSettings, Settings
from .db.session import create_database_engine, create_session_factory
from .providers.deepseek import DeepSeekClient
from .services.chat import ChatService


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings.load()
    engine = create_database_engine(DatabaseSettings.load())
    application.state.session_factory = create_session_factory(engine)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            application.state.chat_service = ChatService(DeepSeekClient(client, settings))
            yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title='大模型对话 Demo', lifespan=lifespan)
    application.include_router(router, prefix='/api')
    return application
