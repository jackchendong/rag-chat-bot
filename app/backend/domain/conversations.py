from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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


class ConversationStore(ABC):
    @abstractmethod
    def login(self, account: str) -> UserInfo:
        raise NotImplementedError

    @abstractmethod
    def get_user(self, user_id: int) -> UserInfo:
        raise NotImplementedError

    @abstractmethod
    def create_conversation(self, user_id: int) -> ConversationInfo:
        raise NotImplementedError

    @abstractmethod
    def list_conversations(self, user_id: int, offset: int, limit: int) -> list[ConversationInfo]:
        raise NotImplementedError

    @abstractmethod
    def list_messages(self, user_id: int, conversation_id: str, before: int | None, limit: int) -> list[MessageInfo]:
        raise NotImplementedError

    @abstractmethod
    def prepare_turn(self, user_id: int, conversation_id: str, message: str) -> PreparedTurn:
        raise NotImplementedError

    @abstractmethod
    def finish_turn(self, turn: PreparedTurn, content: str, status: MessageStatus) -> MessageStatus:
        raise NotImplementedError

    @abstractmethod
    def stop_turn(self, user_id: int, conversation_id: str, assistant_message_id: int) -> bool:
        raise NotImplementedError

    @abstractmethod
    def is_turn_cancelled(self, turn: PreparedTurn) -> bool:
        raise NotImplementedError
