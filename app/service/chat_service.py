import os
from collections.abc import Iterator
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

_chat_model: ChatOpenAI | None = None
_conversation_store: dict[str, list[BaseMessage]] = {}
_conversation_lock = Lock()


def _prepare_messages(
    conversation_id: str,
    message: str,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    with _conversation_lock:
        history = _conversation_store.setdefault(conversation_id, [])
        if system_prompt and not any(isinstance(m, SystemMessage) for m in history):
            history.append(SystemMessage(content=system_prompt))
        history.append(HumanMessage(content=message))
        return list(history)


def _append_ai_message(conversation_id: str, answer: str) -> None:
    with _conversation_lock:
        history = _conversation_store.setdefault(conversation_id, [])
        history.append(AIMessage(content=answer))


def _chunk_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)

    return ""


def _get_chat_model() -> ChatOpenAI:
    global _chat_model
    if _chat_model is not None:
        return _chat_model

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    base_url = os.getenv("OPENAI_API_BASE_URL")

    kwargs = {
        "api_key": api_key,
        "model": model_name,
    }
    if base_url:
        kwargs["base_url"] = base_url

    _chat_model = ChatOpenAI(**kwargs)
    return _chat_model


def chat_with_openai(
    message: str,
    system_prompt: str | None = None,
    conversation_id: str = "default",
) -> str:
    messages = _prepare_messages(conversation_id, message, system_prompt)

    response = _get_chat_model().invoke(messages)
    answer = str(response.content)
    _append_ai_message(conversation_id, answer)
    return answer


def stream_chat_with_openai(
    message: str,
    system_prompt: str | None = None,
    conversation_id: str = "default",
) -> Iterator[str]:
    messages = _prepare_messages(conversation_id, message, system_prompt)
    print(messages)
    answer_parts: list[str] = []
    for chunk in _get_chat_model().stream(messages):
        text = _chunk_to_text(chunk.content)
        if text:
            answer_parts.append(text)
            yield text
    _append_ai_message(conversation_id, "".join(answer_parts))
