from datetime import timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..domain.agent import AgentTaskStore
from ..domain.conversations import PreparedTurn
from ..domain.errors import ConversationError
from ..models import AgentTask, AgentTaskStep, Conversation
from .conversations import ConversationRepository, utc_now


def serialize(row: AgentTask | AgentTaskStep) -> dict[str, Any]:
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if column.name in ('user_id', 'user_message_id', 'assistant_message_id', 'id') and isinstance(value, int):
            value = str(value)
        if column.name.endswith('_at') and value is not None:
            value = value.replace(tzinfo=timezone.utc).isoformat()
        result[column.name] = value
    return result


class AgentTaskRepository(AgentTaskStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.sessions = ConversationRepository(session_factory)

    def start(self, turn: PreparedTurn, model: str, settings: dict[str, Any]) -> str:
        with self.sessions.session() as session:
            conversation = session.get(Conversation, turn.conversation_id)
            if conversation is None:
                raise ConversationError('conversation_not_found', '对话不存在')
            task_id = str(uuid4())
            session.add(AgentTask(id=task_id, user_id=conversation.user_id, conversation_id=turn.conversation_id,
                user_message_id=int(turn.user_message_id), assistant_message_id=int(turn.assistant_message_id),
                status='running', model=model, input_text=turn.messages[-1].content, output_text='',
                settings_snapshot=settings, round_count=0, tool_call_count=0, started_at=utc_now()))
            session.commit()
            return task_id

    def begin_step(self, task_id: str, round_no: int, kind: str, name: str,
                   input_data: dict[str, Any], tool_call_id: str | None = None) -> int:
        with self.sessions.session() as session:
            task = session.scalar(select(AgentTask).where(AgentTask.id == task_id).with_for_update())
            if task is None or task.status != 'running':
                raise ConversationError('task_not_found', '任务不存在或已结束')
            sequence = session.scalar(select(func.max(AgentTaskStep.step_no)).where(AgentTaskStep.task_id == task_id)) or 0
            step = AgentTaskStep(task_id=task_id, step_no=sequence + 1, round_no=round_no, kind=kind,
                name=name, tool_call_id=tool_call_id, status='running', input_data=input_data, started_at=utc_now())
            session.add(step)
            if kind == 'model':
                task.round_count += 1
            elif kind == 'tool':
                task.tool_call_count += 1
            session.flush()
            step_id = step.id
            session.commit()
            return step_id

    def end_step(self, step_id: int, status: str, output: dict[str, Any]) -> None:
        with self.sessions.session() as session:
            step = session.scalar(select(AgentTaskStep).where(AgentTaskStep.id == step_id).with_for_update())
            if step is None or step.status != 'running':
                return
            step.status = status
            step.output_data = output
            step.finished_at = utc_now()
            step.duration_ms = max(0, int((step.finished_at - step.started_at).total_seconds() * 1000))
            session.commit()

    def finish(self, task_id: str, status: str, output: str, error: dict[str, str] | None = None) -> None:
        with self.sessions.session() as session:
            task = session.scalar(select(AgentTask).where(AgentTask.id == task_id).with_for_update())
            if task is None or task.status != 'running':
                return
            task.status, task.output_text, task.error = status, output, error
            task.finished_at = utc_now()
            # Finalize open steps on disconnect or a storage/tool/model error.
            for step in session.scalars(select(AgentTaskStep).where(
                    AgentTaskStep.task_id == task_id, AgentTaskStep.status == 'running').with_for_update()):
                step.status = 'cancelled' if status == 'cancelled' else 'failed'
                step.output_data = {'error': error or {'code': 'interrupted', 'message': '步骤执行中断'}}
                step.finished_at = task.finished_at
                step.duration_ms = max(0, int((step.finished_at - step.started_at).total_seconds() * 1000))
            session.commit()

    def list_tasks(self, user_id: int, conversation_id: str | None, offset: int, limit: int) -> list[dict[str, Any]]:
        with self.sessions.session() as session:
            query = select(AgentTask).where(AgentTask.user_id == user_id)
            if conversation_id is not None:
                self.sessions.owned_conversation(session, user_id, conversation_id)
                query = query.where(AgentTask.conversation_id == conversation_id)
            rows = session.scalars(query.order_by(AgentTask.created_at.desc(), AgentTask.id.desc()).offset(offset).limit(limit))
            return [{key: value for key, value in serialize(row).items()
                     if key not in ('settings_snapshot', 'input_text', 'output_text')} for row in rows]

    def detail(self, user_id: int, task_id: str, offset: int, limit: int) -> dict[str, Any]:
        with self.sessions.session() as session:
            task = session.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id))
            if task is None:
                raise ConversationError('task_not_found', '任务不存在')
            steps = session.scalars(select(AgentTaskStep).where(AgentTaskStep.task_id == task_id)
                .order_by(AgentTaskStep.step_no).offset(offset).limit(limit))
            return {'task': serialize(task), 'steps': [serialize(step) for step in steps], 'offset': offset, 'limit': limit}
