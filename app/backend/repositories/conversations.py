from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from ..domain.chat import ModelMessage
from ..domain.conversations import ConversationInfo, ConversationStore, MessageInfo, MessageStatus, PreparedTurn, UserInfo
from ..domain.errors import ConversationError
from ..models import Conversation, Message, User, ScheduledRun, ScheduledTask


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def conversation_info(conversation: Conversation) -> ConversationInfo:
    return ConversationInfo(conversation.id, conversation.title, conversation.updated_at.replace(tzinfo=timezone.utc))


class ConversationRepository(ConversationStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        try:
            with self.session_factory() as session:
                yield session
        except SQLAlchemyError:
            raise ConversationError('storage_unavailable', '数据库操作失败，请确认迁移已执行并稍后重试') from None

    def login(self, account: str) -> UserInfo:
        with self.session() as session:
            user = session.scalar(select(User).where(User.account == account))
            if user is None:
                user = User(account=account)
                session.add(user)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    user = session.scalar(select(User).where(User.account == account))
                    if user is None:
                        raise ConversationError('storage_unavailable', '账号创建失败，请稍后重试') from None
            return UserInfo(str(user.id), user.account)

    def get_user(self, user_id: int) -> UserInfo:
        with self.session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise ConversationError('invalid_user', '用户不存在，请重新登录')
            return UserInfo(str(user.id), user.account)

    def owned_conversation(self, session: Session, user_id: int, conversation_id: str, *, lock: bool = False) -> Conversation:
        query = select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        if lock:
            query = query.with_for_update()
        conversation = session.scalar(query)
        if conversation is None:
            raise ConversationError('conversation_not_found', '对话不存在')
        return conversation

    def create_conversation(self, user_id: int) -> ConversationInfo:
        with self.session() as session:
            conversation = Conversation(id=str(uuid4()), user_id=user_id, title='新对话')
            session.add(conversation)
            session.commit()
            return conversation_info(conversation)

    def list_conversations(self, user_id: int, offset: int, limit: int) -> list[ConversationInfo]:
        with self.session() as session:
            rows = session.scalars(select(Conversation).where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc()).offset(offset).limit(limit))
            return [conversation_info(row) for row in rows]

    def list_messages(self, user_id: int, conversation_id: str, before: int | None, limit: int) -> list[MessageInfo]:
        with self.session() as session:
            self.owned_conversation(session, user_id, conversation_id)
            query = select(Message).where(Message.conversation_id == conversation_id)
            if before is not None:
                query = query.where(Message.id < before)
            rows = list(session.scalars(query.order_by(Message.id.desc()).limit(limit)))
            return [MessageInfo(str(row.id), row.role, row.content, row.status,
                row.created_at.replace(tzinfo=timezone.utc)) for row in reversed(rows)]

    def prepare_turn(self, user_id: int, conversation_id: str, message: str,
                     scheduled_run_id: str | None = None) -> PreparedTurn:
        with self.session() as session:
            scheduled_run = None
            if scheduled_run_id:
                scheduled_run = session.scalar(select(ScheduledRun).where(ScheduledRun.id == scheduled_run_id).with_for_update())
                task = session.get(ScheduledTask, scheduled_run.task_id) if scheduled_run else None
                if (not scheduled_run or scheduled_run.status != 'running' or scheduled_run.assistant_message_id
                        or not task or task.user_id != user_id or task.conversation_id != conversation_id):
                    raise ConversationError('task_busy', '执行记录已失效或已关联消息')
            conversation = self.owned_conversation(session, user_id, conversation_id, lock=True)
            if conversation.active_message_id is not None:
                active = session.get(Message, conversation.active_message_id)
                if active is not None and active.status == 'generating':
                    if active.created_at > utc_now() - timedelta(minutes=5):
                        raise ConversationError('conversation_busy', '当前对话正在生成回答，请稍后再试')
                    active.status = 'failed'
            recent = list(session.scalars(select(Message).where(Message.conversation_id == conversation_id)
                .order_by(Message.id.desc()).limit(40)))
            pairs: list[list[ModelMessage]] = []
            ordered = list(reversed(recent))
            for position in range(len(ordered) - 1):
                user_message, assistant_message = ordered[position:position + 2]
                if user_message.role == 'user' and assistant_message.role == 'assistant' and assistant_message.status == 'completed':
                    pairs.append([ModelMessage('user', user_message.content), ModelMessage('assistant', assistant_message.content)])
            history: list[ModelMessage] = []
            size = len(message)
            for pair in reversed(pairs):
                pair_size = sum(len(item.content) for item in pair)
                if size + pair_size > 30000:
                    break
                history[0:0] = pair
                size += pair_size
            first_message = not recent
            user_message = Message(conversation_id=conversation_id, role='user', content=message, status='completed')
            assistant_message = Message(conversation_id=conversation_id, role='assistant', content='', status='generating')
            session.add_all([user_message, assistant_message])
            session.flush()
            if scheduled_run:
                scheduled_run.user_message_id = user_message.id
                scheduled_run.assistant_message_id = assistant_message.id
            conversation.active_message_id = assistant_message.id
            conversation.updated_at = utc_now()
            if first_message:
                conversation.title = ' '.join(message.split())[:80]
            turn = PreparedTurn(conversation_id, str(user_message.id), str(assistant_message.id), history + [ModelMessage('user', message)])
            session.commit()
            return turn

    def stop_turn(self, user_id: int, conversation_id: str, assistant_message_id: int) -> bool:
        with self.session() as session:
            conversation = self.owned_conversation(session, user_id, conversation_id, lock=True)
            message = session.get(Message, assistant_message_id)
            if message is None or message.conversation_id != conversation_id or message.role != 'assistant':
                raise ConversationError('conversation_not_found', '回答记录不存在')
            if message.status == 'cancelled':
                return True
            if conversation.active_message_id != assistant_message_id or message.status != 'generating':
                return False
            message.status = 'cancelled'
            conversation.updated_at = utc_now()
            session.commit()
            return True

    def is_turn_cancelled(self, turn: PreparedTurn) -> bool:
        with self.session() as session:
            message = session.get(Message, int(turn.assistant_message_id))
            return message is not None and message.status == 'cancelled'

    def finish_turn(self, turn: PreparedTurn, content: str, status: MessageStatus) -> MessageStatus:
        with self.session() as session:
            conversation = session.scalar(select(Conversation).where(Conversation.id == turn.conversation_id).with_for_update())
            message = session.get(Message, int(turn.assistant_message_id))
            if conversation is None or conversation.active_message_id != int(turn.assistant_message_id):
                # A stopped older stream can finish after a new turn has started.
                # Preserve its partial text without releasing the new turn's marker.
                if message is not None and message.status == 'cancelled':
                    if content:
                        message.content = content
                        session.commit()
                    return 'cancelled'
                if status == 'cancelled':
                    return message.status if message is not None else 'cancelled'
                raise ConversationError('conversation_busy', '回答已过期，请刷新对话')
            if message is None:
                raise ConversationError('conversation_not_found', '回答记录不存在')
            if message.status == 'cancelled':
                status = 'cancelled'
            message.content = content
            message.status = status
            conversation.active_message_id = None
            conversation.updated_at = utc_now()
            session.commit()
            return status
