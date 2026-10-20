import asyncio
import logging
from contextlib import aclosing

from ..domain.errors import ConversationError
from ..domain.schedule import ScheduleStore, ScheduledExecution
from .chat import ChatService

logger = logging.getLogger(__name__)


class ScheduleRunner:
    def __init__(self, store: ScheduleStore, chat: ChatService) -> None:
        self.store, self.chat = store, chat
        self.active_ticks: set[asyncio.Task[None]] = set()
        self.workers: set[asyncio.Task[None]] = set()

    def completed(self, worker: asyncio.Task[None]) -> None:
        self.workers.discard(worker)
        if not worker.cancelled() and (failure := worker.exception()) is not None:
            logger.error('Scheduled worker failed worker=%s type=%s', worker.get_name(), type(failure).__name__)

    async def wait(self) -> None:
        if self.workers:
            await asyncio.gather(*tuple(self.workers))

    async def close(self) -> None:
        workers = tuple(self.workers)
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

    async def execute(self, execution: ScheduledExecution) -> None:
        status, error = 'failed', '执行未完成'
        logger.info('Scheduled execution started run=%s', execution.run_id)

        async def consume() -> None:
            nonlocal status, error
            run = await self.chat.prepare(execution.user_id, execution.conversation_id,
                execution.prompt, scheduled_run_id=execution.run_id)
            async with aclosing(self.chat.answer(run)) as events:
                async for event in events:
                    if event.event == 'error':
                        error = str(event.data['message'])
                    elif event.event == 'done':
                        status = 'cancelled' if event.data.get('cancelled') else 'completed'
                        error = None
        try:
            # Include preparation in the budget; ChatService's own deadline begins after preparation.
            await asyncio.wait_for(consume(), timeout=self.chat.policy.timeout_seconds)
        except asyncio.TimeoutError:
            status, error = 'failed', '任务执行超过总时间限制，已终止；未自动重试'
            logger.warning('Scheduled execution timed out run=%s', execution.run_id)
        except ConversationError as failure:
            error = failure.message
        except asyncio.CancelledError:
            status = 'cancelled'
            error = '服务关闭，执行已中断'
            raise
        except Exception as failure:
            # Never log exception text: provider/DB exceptions can contain credentials.
            logger.error('Scheduled execution failed run=%s type=%s', execution.run_id, type(failure).__name__)
            error = '执行异常，请查看会话记录或稍后手动运行'
        finally:
            await self.persist_finished(execution.run_id, status, error)
            logger.info('Scheduled execution finalization saved run=%s requested_status=%s', execution.run_id, status)

    async def persist_finished(self, run_id: str, status: str, error: str | None) -> None:
        # Retry only the idempotent terminal-state write, never the model/tools.
        for attempt in range(3):
            try:
                await self.chat.database(self.store.finish, run_id, status, error)
                return
            except ConversationError as failure:
                if failure.code != 'storage_unavailable' or attempt == 2:
                    raise
                logger.warning('Retry scheduled result persistence run=%s attempt=%s', run_id, attempt + 1)
                await asyncio.sleep(0.25 * (attempt + 1))

    async def tick(self) -> None:
        current = asyncio.current_task()
        if current:
            self.active_ticks.add(current)
        try:
            await self.chat.database(self.store.recover)
            for _ in range(max(0, 4 - len(self.workers))):
                execution = await self.chat.database(self.store.claim)
                if execution is None:
                    break
                worker = asyncio.create_task(self.execute(execution), name=f'scheduled:{execution.run_id}')
                self.workers.add(worker)
                worker.add_done_callback(self.completed)
        except ConversationError as failure:
            logger.warning('Scheduler storage unavailable code=%s', failure.code)
        finally:
            if current:
                self.active_ticks.discard(current)
