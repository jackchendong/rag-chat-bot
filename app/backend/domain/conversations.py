from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from .chat import ModelMessage

MessageStatus = Literal['generating', 'completed', 'failed', 'cancelled']


@dataclass(frozen=True)
class UserInfo:
    user_id: str
    account: str


@dataclass(frozen=True)
class ConversationInfo:
    conversation_id: str
    title: str
    updated_at: datetime


@dataclass(frozen=True)
class MessageInfo:
    id: str
    role: Literal['user', 'assistant']
    content: str
    status: MessageStatus
    created_at: datetime


@dataclass(frozen=True)
class PreparedTurn:
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    messages: list[ModelMessage]


class ConversationStore(Protocol):
    def login(self, account: str) -> UserInfo: ...
    def get_user(self, user_id: int) -> UserInfo: ...
    def create_conversation(self, user_id: int) -> ConversationInfo: ...
    def list_conversations(self, user_id: int, offset: int, limit: int) -> list[ConversationInfo]: ...
    def list_messages(self, user_id: int, conversation_id: str, before: int | None, limit: int) -> list[MessageInfo]: ...
    def prepare_turn(self, user_id: int, conversation_id: str, message: str) -> PreparedTurn: ...
    def finish_turn(self, turn: PreparedTurn, content: str, status: MessageStatus) -> MessageStatus: ...
    def stop_turn(self, user_id: int, conversation_id: str, assistant_message_id: int) -> bool: ...
    def is_turn_cancelled(self, turn: PreparedTurn) -> bool: ...
