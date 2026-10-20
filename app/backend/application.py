import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .api.routes.chat import router
from .api.routes.conversations import router as conversation_router
from .api.routes.agent import router as agent_router
from .api.routes.schedules import router as schedule_router
from .repositories.schedules import ScheduleRepository
from .services.schedules import ScheduleRunner
from .core.config import AgentSettings, DatabaseSettings, Settings
from .core.logging import configure_logging
from .db.session import create_database_engine, create_session_factory
from .providers.deepseek import DeepSeekClient
from .services.chat import ChatService
from .domain.errors import ConversationError
from .repositories.conversations import ConversationRepository
from .repositories.agent_tasks import AgentTaskRepository
from .tools.registry import ToolRegistry
from .tools.skills import FileSkillSource, LoadSkillTool
from .tools.web import TavilyTool
from .tools.public_web import PublicWebTool
from .tools.weather import OpenMeteoWeatherTool
from .tools.shell import ShellTool
from .tools.schedules import CreateScheduledTaskTool
from .domain.agent import Tool


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    settings = Settings.load()
    agent = AgentSettings.load()
    skills = FileSkillSource(agent.resolve_path(agent.skills_dir))
    skills.catalog()  # Validate trusted local skills before accepting requests; no network/DB access.
    engine = create_database_engine(DatabaseSettings.load())
    application.state.session_factory = create_session_factory(engine)
    application.state.conversation_store = ConversationRepository(application.state.session_factory)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout, connect=10),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        ) as client:
            application.state.schedule_store = ScheduleRepository(application.state.session_factory)
            tools: list[Tool] = [LoadSkillTool(skills), CreateScheduledTaskTool(application.state.schedule_store)]
            if agent.weather_enabled:
                tools.append(OpenMeteoWeatherTool(client))
            if agent.web_enabled:
                use_tavily = agent.web_provider == 'tavily' or (
                    agent.web_provider == 'auto' and bool(agent.tavily_api_key.get_secret_value().strip()))
                if use_tavily:
                    tools.extend([TavilyTool(client, agent.tavily_api_key.get_secret_value()),
                                  TavilyTool(client, agent.tavily_api_key.get_secret_value(), read=True)])
                else:
                    tools.extend([PublicWebTool(client), PublicWebTool(client, read=True)])
            if agent.shell_enabled:
                tools.append(ShellTool(agent.resolve_path(agent.shell_workspace), agent.shell_allowlist,
                                       agent.max_tool_output_chars))
            application.state.chat_service = ChatService(DeepSeekClient(client, settings),
                application.state.conversation_store, AgentTaskRepository(application.state.session_factory),
                ToolRegistry(tools), skills, agent.policy(), settings.model)
            runner = ScheduleRunner(application.state.schedule_store, application.state.chat_service)
            scheduler = AsyncIOScheduler(timezone='UTC')
            # Only the periodic wakeup is in memory. All business schedules/claims live in MySQL.
            scheduler.add_job(runner.tick, 'interval', seconds=2, id='persistent-schedule-poll',
                coalesce=True, max_instances=1, misfire_grace_time=30)
            scheduler.start()
            try:
                yield
            finally:
                scheduler.pause()
                pending = tuple(runner.active_ticks)
                scheduler.shutdown(wait=False)
                # AsyncIOScheduler.shutdown cancels its futures; wait for DB/model cleanup.
                await asyncio.sleep(0)
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                await runner.close()
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title='大模型对话 Demo',
        lifespan=lifespan,
        docs_url='/docs',
        redoc_url='/api/redoc',
        openapi_url='/api/openapi.json',
        swagger_ui_oauth2_redirect_url='/docs/oauth2-redirect',
    )
    application.include_router(router, prefix='/api')
    application.include_router(conversation_router, prefix='/api')
    application.include_router(agent_router, prefix='/api')
    application.include_router(schedule_router, prefix='/api')
    application.add_exception_handler(ConversationError, handle_conversation_error)
    static_directory = Path(__file__).resolve().parents[1] / 'static'
    application.mount('/static', StaticFiles(directory=static_directory, html=True), name='static')

    @application.middleware('http')
    async def redirect_to_frontend(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path.startswith(('/api', '/docs', '/static/')):
            return await call_next(request)
        return RedirectResponse(url=request.url_for('static', path='index.html'), status_code=307)

    return application


async def handle_conversation_error(request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ConversationError):
        return JSONResponse(status_code=500, content={'code': 'internal_error', 'message': '服务暂不可用'})
    status = {
        'invalid_user': 401,
        'conversation_not_found': 404,
        'conversation_busy': 409,
        'storage_unavailable': 503,
        'task_not_found': 404,
        'invalid_skill': 400,
        'invalid_schedule': 400,
        'task_busy': 409,
    }.get(error.code, 500)
    return JSONResponse(status_code=status, content={'code': error.code, 'message': error.message})
