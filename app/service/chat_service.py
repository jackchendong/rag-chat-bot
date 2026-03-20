import os
from collections.abc import Iterator
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

_chat_model: ChatOpenAI | None = None


def _build_messages(message: str, system_prompt: str | None = None) -> list[SystemMessage | HumanMessage]:
    messages: list[SystemMessage | HumanMessage] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=message))
    return messages


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


def chat_with_openai(message: str, system_prompt: str | None = None) -> str:
    messages = _build_messages(message, system_prompt)

    response = _get_chat_model().invoke(messages)
    return str(response.content)


def stream_chat_with_openai(message: str, system_prompt: str | None = None) -> Iterator[str]:
    messages = _build_messages(message, system_prompt)
    for chunk in _get_chat_model().stream(messages):
        text = _chunk_to_text(chunk.content)
        if text:
            yield text
