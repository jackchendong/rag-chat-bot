import os
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

load_dotenv()

_chat_model: ChatOpenAI | None = None
_summary_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-summary")

MAX_RECENT_TURNS = 3
MAX_RECENT_MESSAGES = MAX_RECENT_TURNS * 2
SUMMARY_TRIGGER_TURNS = 3


@dataclass
class ConversationState:
    system_prompt: str | None = None
    summary: str = ""
    recent_messages: list[BaseMessage] = field(default_factory=list)
    unsummarized_messages: list[BaseMessage] = field(default_factory=list)
    summarizing: bool = False


_conversation_store: dict[str, ConversationState] = {}
_conversation_lock = Lock()

_chat_prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_content}"),
        MessagesPlaceholder("recent_messages"),
    ]
)

_summary_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a conversation summarizer. Keep important facts, constraints, and user intent. "
            "Output concise summary text only.",
        ),
        (
            "user",
            "Current summary:\n{previous_summary}\n\n"
            "New conversation segment:\n{dialogue}\n\n"
            "Produce an updated summary in under 180 words.",
        ),
    ]
)


def _get_state(conversation_id: str) -> ConversationState:
    return _conversation_store.setdefault(conversation_id, ConversationState())


def _completed_turns(messages: list[BaseMessage]) -> int:
    human_count = sum(isinstance(m, HumanMessage) for m in messages)
    ai_count = sum(isinstance(m, AIMessage) for m in messages)
    return min(human_count, ai_count)


def _messages_to_dialogue(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            role = "user"
        elif isinstance(message, AIMessage):
            role = "assistant"
        elif isinstance(message, SystemMessage):
            role = "system"
        else:
            role = "other"
        lines.append(f"{role}: {str(message.content)}")
    return "\n".join(lines)


def _build_system_content(system_prompt: str | None, summary: str) -> str:
    base_system = system_prompt or "你是一个专业的 AI 工程助手。"
    if not summary:
        return base_system

    return (
        f"{base_system}\n\n"
        "Conversation summary:\n"
        f"{summary}"
    )


def _run_summary_job(
    conversation_id: str,
    previous_summary: str,
    snapshot_messages: list[BaseMessage],
) -> None:
    try:
        dialogue = _messages_to_dialogue(snapshot_messages)
        summary_messages = _summary_prompt_template.format_messages(
            previous_summary=previous_summary or "(empty)",
            dialogue=dialogue,
        )
        summary_response = _get_chat_model().invoke(summary_messages)
        updated_summary = str(summary_response.content).strip()
    except Exception:
        with _conversation_lock:
            state = _conversation_store.get(conversation_id)
            if state:
                state.summarizing = False
        return

    with _conversation_lock:
        state = _conversation_store.get(conversation_id)
        if not state:
            return

        consume_count = min(len(snapshot_messages), len(state.unsummarized_messages))
        state.unsummarized_messages = state.unsummarized_messages[consume_count:]
        if updated_summary:
            state.summary = updated_summary
        state.summarizing = False

    _maybe_schedule_summary(conversation_id)


def _maybe_schedule_summary(conversation_id: str) -> None:
    with _conversation_lock:
        state = _conversation_store.get(conversation_id)
        if not state:
            return

        if state.summarizing:
            return

        if _completed_turns(state.unsummarized_messages) < SUMMARY_TRIGGER_TURNS:
            return

        snapshot_messages = list(state.unsummarized_messages)
        previous_summary = state.summary
        state.summarizing = True

    _summary_executor.submit(
        _run_summary_job,
        conversation_id,
        previous_summary,
        snapshot_messages,
    )


def _prepare_messages(
    conversation_id: str,
    message: str,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    with _conversation_lock:
        state = _get_state(conversation_id)
        if system_prompt:
            state.system_prompt = system_prompt

        state.recent_messages.append(HumanMessage(content=message))
        state.unsummarized_messages.append(HumanMessage(content=message))
        state.recent_messages = state.recent_messages[-MAX_RECENT_MESSAGES:]

        system_content = _build_system_content(state.system_prompt, state.summary)
        prompt_messages = _chat_prompt_template.format_messages(
            system_content=system_content,
            recent_messages=list(state.recent_messages),
        )

    return prompt_messages


def _append_ai_message(conversation_id: str, answer: str) -> None:
    with _conversation_lock:
        state = _get_state(conversation_id)
        state.recent_messages.append(AIMessage(content=answer))
        state.recent_messages = state.recent_messages[-MAX_RECENT_MESSAGES:]
        state.unsummarized_messages.append(AIMessage(content=answer))

    _maybe_schedule_summary(conversation_id)


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
    print("\n---\n")
    answer_parts: list[str] = []
    for chunk in _get_chat_model().stream(messages):
        text = _chunk_to_text(chunk.content)
        if text:
            answer_parts.append(text)
            yield text
    _append_ai_message(conversation_id, "".join(answer_parts))
