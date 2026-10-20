from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from ..domain.errors import ConversationError
from ..domain.schedule import ScheduledExecution
from ..models import AgentTask, AgentTaskStep, Conversation, Message, ScheduledRun, ScheduledTask
from .conversations import ConversationRepository, utc_now


def next_fire(kind: str, cron: str | None, zone: str, run_at: datetime | None,
              now: datetime) -> datetime | None:
    if kind == 'once':
        return run_at
    trigger = CronTrigger.from_crontab(cron or '', timezone=ZoneInfo(zone))
    result = trigger.get_next_fire_time(None, now.replace(tzinfo=timezone.utc) + timedelta(seconds=1))
    # APScheduler can return imaginary wall times during a DST spring transition.
    while result and result.astimezone(timezone.utc).astimezone(ZoneInfo(zone)).replace(tzinfo=None) != result.replace(tzinfo=None):
        result = trigger.get_next_fire_time(result, result + timedelta(seconds=1))
    return result.astimezone(timezone.utc).replace(tzinfo=None) if result else None


def iso(value: datetime | None) -> str | None:
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


def task_data(row: ScheduledTask) -> dict[str, Any]:
    return {key: getattr(row, key) for key in ('id', 'conversation_id', 'name', 'prompt', 'kind', 'timezone', 'cron', 'status')} | {
        'run_at': iso(row.run_at), 'next_run_at': iso(row.next_run_at), 'created_at': iso(row.created_at)}


def run_data(row: ScheduledRun, message: Message | None = None) -> dict[str, Any]:
    return {key: getattr(row, key) for key in ('id', 'task_id', 'source', 'status', 'error', 'prompt')} | {
        'scheduled_at': iso(row.scheduled_at), 'started_at': iso(row.started_at), 'finished_at': iso(row.finished_at),
        'assistant_message_id': str(row.assistant_message_id) if row.assistant_message_id else None,
        'message_status': message.status if message else None,
        'result_preview': message.content[:2000] if message else None,
        'result_truncated': bool(message and len(message.content) > 2000)}


class ScheduleRepository(ConversationRepository):
    def owned_task(self, session: Session, user_id: int, task_id: str, lock: bool = False) -> ScheduledTask:
        query = select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.user_id == user_id)
        row = session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ConversationError('task_not_found', '定时任务不存在')
        return row

    def list_tasks(self, user_id: int, conversation_id: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
        with self.session() as session:
            query = select(ScheduledTask).where(ScheduledTask.user_id == user_id)
            if conversation_id:
                self.owned_conversation(session, user_id, conversation_id)
                query = query.where(ScheduledTask.conversation_id == conversation_id)
            return [task_data(row) for row in session.scalars(query.order_by(
                ScheduledTask.created_at.desc(), ScheduledTask.id.desc()).offset(offset).limit(limit))]

    def save(self, user_id: int, data: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
        with self.session() as session:
            if task_id:
                row = self.owned_task(session, user_id, task_id, True)
            else:
                # Serialize create requests per conversation; request_id also has a DB unique constraint.
                conversation_id = str(data['conversation_id'])
                self.owned_conversation(session, user_id, conversation_id, lock=True)
                row = session.scalar(select(ScheduledTask).where(ScheduledTask.user_id == user_id,
                    ScheduledTask.request_id == str(data['request_id'])))
                if row:
                    return task_data(row)
                row = ScheduledTask(id=str(uuid4()), user_id=user_id, conversation_id=conversation_id,
                    request_id=str(data['request_id']), status='active')
                session.add(row)
            # Check after deduplication so retrying a saved once-task also works after its due time.
            if data['kind'] == 'once' and data['run_at'] <= datetime.now(timezone.utc):
                raise ConversationError('invalid_schedule', '执行时间必须晚于当前时间')
            for key in ('name', 'prompt', 'kind', 'timezone', 'cron'):
                setattr(row, key, data[key])
            run_at = data['run_at']
            row.run_at = run_at.astimezone(timezone.utc).replace(tzinfo=None) if run_at else None
            if row.status == 'completed':
                row.status = 'active'
            row.next_run_at = next_fire(row.kind, row.cron, row.timezone, row.run_at, utc_now()) if row.status == 'active' else None
            session.commit()
            return task_data(row)

    def set_state(self, user_id: int, task_id: str, status: str) -> dict[str, Any]:
        with self.session() as session:
            row = self.owned_task(session, user_id, task_id, True)
            if status == 'active' and row.kind == 'once' and row.run_at <= utc_now():
                raise ConversationError('invalid_schedule', '一次性执行时间已过，请先编辑未来时间')
            row.status = status
            row.next_run_at = next_fire(row.kind, row.cron, row.timezone, row.run_at, utc_now()) if status == 'active' else None
            session.commit()
            return task_data(row)

    def enqueue(self, user_id: int, task_id: str, request_id: str) -> dict[str, Any]:
        with self.session() as session:
            task = self.owned_task(session, user_id, task_id, True)
            previous = session.scalar(select(ScheduledRun).where(ScheduledRun.task_id == task.id,
                ScheduledRun.request_id == request_id))
            if previous:
                return run_data(previous)
            pending = session.scalar(select(ScheduledRun.id).where(ScheduledRun.task_id == task.id,
                ScheduledRun.status.in_(['queued', 'running'])).limit(1))
            if pending:
                raise ConversationError('task_busy', '任务正在排队或执行，请稍后再试')
            run = ScheduledRun(id=str(uuid4()), task_id=task.id, request_id=request_id,
                source='manual', prompt=task.prompt, status='queued', scheduled_at=utc_now())
            session.add(run)
            session.commit()
            return run_data(run)

    def runs(self, user_id: int, task_id: str, offset: int, limit: int) -> list[dict[str, Any]]:
        with self.session() as session:
            self.owned_task(session, user_id, task_id)
            rows = session.execute(select(ScheduledRun, Message).outerjoin(Message,
                Message.id == ScheduledRun.assistant_message_id).where(ScheduledRun.task_id == task_id)
                .order_by(ScheduledRun.created_at.desc(), ScheduledRun.id.desc()).offset(offset).limit(limit))
            return [run_data(row, message) for row, message in rows]

    def claim(self) -> ScheduledExecution | None:
        now = utc_now()
        with self.session() as session:
            running = exists().where(ScheduledRun.task_id == ScheduledTask.id, ScheduledRun.status == 'running')
            queued = exists().where(ScheduledRun.task_id == ScheduledTask.id, ScheduledRun.status == 'queued')
            due = (ScheduledTask.status == 'active') & (ScheduledTask.next_run_at <= now)
            conversation_busy = exists().where(Message.conversation_id == ScheduledTask.conversation_id,
                Message.status == 'generating', Message.created_at > now - timedelta(minutes=5))
            task = session.scalar(select(ScheduledTask).where(~running, ~conversation_busy, or_(queued, due))
                .order_by(ScheduledTask.next_run_at, ScheduledTask.id).with_for_update(skip_locked=True).limit(1))
            if task is None:
                return None
            run = session.scalar(select(ScheduledRun).where(ScheduledRun.task_id == task.id,
                ScheduledRun.status == 'queued').order_by(ScheduledRun.created_at).with_for_update().limit(1))
            if run is None:
                run = ScheduledRun(id=str(uuid4()), task_id=task.id, request_id=str(uuid4()), source='scheduled',
                    prompt=task.prompt, status='running', scheduled_at=task.next_run_at)
                session.add(run)
                # Coalesce overdue occurrences to one, then calculate from now.
                task.next_run_at = None if task.kind == 'once' else next_fire(task.kind, task.cron, task.timezone, None, now)
                if task.next_run_at is None:
                    task.status = 'completed'
            run.status = 'running'
            run.started_at = now
            session.commit()
            return ScheduledExecution(run.id, task.user_id, task.conversation_id, run.prompt)

    def finish(self, run_id: str, status: str, error: str | None) -> None:
        with self.session() as session:
            run = session.scalar(select(ScheduledRun).where(ScheduledRun.id == run_id).with_for_update())
            if not run or run.status != 'running':
                return
            self.settle_run(session, run, status, error)
            session.commit()

    def settle_run(self, session: Session, run: ScheduledRun, status: str, error: str | None) -> None:
        run.status, run.error, run.finished_at = status, error, utc_now()
        if not run.assistant_message_id:
            self.failure_messages(session, run)
            return
        task = session.get(ScheduledTask, run.task_id)
        conversation = session.scalar(select(Conversation).where(Conversation.id == task.conversation_id).with_for_update())
        message = session.get(Message, run.assistant_message_id)
        if message:
            if message.status == 'completed':
                # Preserve a result committed before a later audit/run persistence error.
                run.status, run.error = 'completed', None
            elif message.status == 'cancelled' and status != 'failed':
                run.status = 'cancelled'
            elif message.status == 'failed':
                run.status = 'failed'
            else:
                message.status = run.status
            if run.status == 'failed' and run.error:
                note = '定时任务执行失败：' + run.error
                if note not in message.content:
                    message.content = (message.content + '\n\n' + note).strip()
        if conversation.active_message_id == run.assistant_message_id:
            conversation.active_message_id = None
        conversation.updated_at = utc_now()
        audit = session.scalar(select(AgentTask).where(AgentTask.assistant_message_id == run.assistant_message_id).with_for_update())
        if audit and (audit.status == 'running' or (audit.status == 'cancelled' and run.status == 'failed')):
            audit.status, audit.finished_at = run.status, run.finished_at
            audit.output_text = message.content if message else ''
            audit.error = {'code': 'schedule_interrupted', 'message': run.error} if run.error else None
            session.execute(update(AgentTaskStep).where(AgentTaskStep.task_id == audit.id,
                AgentTaskStep.status == 'running').values(
                    status='cancelled' if run.status == 'cancelled' else 'failed', finished_at=run.finished_at))

    def failure_messages(self, session: Session, run: ScheduledRun) -> None:
        task = session.get(ScheduledTask, run.task_id)
        conversation = session.scalar(select(Conversation).where(Conversation.id == task.conversation_id).with_for_update())
        prompt = Message(conversation_id=task.conversation_id, role='user', content=run.prompt, status='completed')
        answer = Message(conversation_id=task.conversation_id, role='assistant',
            content=('定时任务已取消：' if run.status == 'cancelled' else '定时任务执行失败：') + (run.error or '执行中断'),
            status='cancelled' if run.status == 'cancelled' else 'failed')
        session.add_all([prompt, answer])
        session.flush()
        run.user_message_id, run.assistant_message_id = prompt.id, answer.id
        conversation.updated_at = utc_now()

    def recover(self) -> None:
        # No automatic replay of a possibly completed external side effect.
        with self.session() as session:
            terminal_message = exists().where(Message.id == ScheduledRun.assistant_message_id,
                Message.status.in_(['completed', 'failed', 'cancelled']))
            rows = session.scalars(select(ScheduledRun).where(ScheduledRun.status == 'running', or_(
                terminal_message, ScheduledRun.started_at < utc_now() - timedelta(minutes=10)))
                .with_for_update(skip_locked=True).limit(50))
            for run in rows:
                message = session.get(Message, run.assistant_message_id) if run.assistant_message_id else None
                status = message.status if message and message.status != 'generating' else 'failed'
                error = None if status in ('completed', 'cancelled') else '执行中断或超过恢复期限，未自动重试'
                self.settle_run(session, run, status, error)
            session.commit()
