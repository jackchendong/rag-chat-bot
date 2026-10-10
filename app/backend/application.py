from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .api.routes.chat import router
from .api.routes.conversations import router as conversation_router
from .core.config import DatabaseSettings, Settings
from .db.session import create_database_engine, create_session_factory
from .providers.deepseek import DeepSeekClient
from .services.chat import ChatService
from .domain.errors import ConversationError
from .repositories.conversations import ConversationRepository


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    settings = Settings.load()
    engine = create_database_engine(DatabaseSettings.load())
    application.state.session_factory = create_session_factory(engine)
    application.state.conversation_store = ConversationRepository(application.state.session_factory)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            application.state.chat_service = ChatService(DeepSeekClient(client, settings), application.state.conversation_store)
            yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(title='大模型对话 Demo', lifespan=lifespan)
    application.include_router(router, prefix='/api')
    application.include_router(conversation_router, prefix='/api')
    application.add_exception_handler(ConversationError, handle_conversation_error)
    static_directory = Path(__file__).resolve().parents[1] / 'static'
    application.mount('/static', StaticFiles(directory=static_directory, html=True), name='static')
    return application


async def handle_conversation_error(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ConversationError):
        return JSONResponse(status_code=500, content={'code': 'internal_error', 'message': '服务暂不可用'})
    status = {
        'invalid_user': 401,
        'conversation_not_found': 404,
        'conversation_busy': 409,
        'storage_unavailable': 503,
    }.get(error.code, 500)
    return JSONResponse(status_code=status, content={'code': error.code, 'message': error.message})
