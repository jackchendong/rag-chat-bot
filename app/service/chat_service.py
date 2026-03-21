import os
import json
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
    pending_rewritten_question: str | None = None


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

_rewrite_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是一个对话改写助手。
你的任务是根据最近对话，消除用户当前问题中的代词、指代和省略，
把问题改写成一个语义明确、可独立理解的问题。

要求：
1. 不要改变用户原意
2. 如果当前问题已经足够明确，就尽量少改
3. 输出只能是改写后的问题，不要解释
""",
        ),
        (
            "user",
            """最近对话：
{recent_dialogue}

当前问题：
{question}
""",
        ),
    ]
)

_clarity_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是问题明确性判断助手。判断问题是否足够明确、可独立理解。"
            "只输出 JSON："
            '{{"needs_confirmation": true/false, "question": "问题文本"}}',
        ),
        (
            "user",
            "最近对话：\n{recent_dialogue}\n\n"
            "改写后的问题：\n{rewritten_question}",
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


def _recent_dialogue_text(messages: list[BaseMessage]) -> str:
    text = _messages_to_dialogue(messages[-MAX_RECENT_MESSAGES:])
    return text if text.strip() else "(empty)"


def _safe_json_loads(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    if not text:
        return None

    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start : end + 1])
        if isinstance(data, dict):
            return data
    except Exception:
        return None

    return None


def _is_confirmation_text(message: str) -> bool:
    normalized = message.strip().lower()
    return normalized in {
        "确认",
        "是",
        "是的",
        "对",
        "对的",
        "yes",
        "y",
        "ok",
        "okay",
    }


def _rewrite_question(recent_dialogue: str, question: str) -> str:
    prompt_messages = _rewrite_prompt_template.format_messages(
        recent_dialogue=recent_dialogue,
        question=question,
    )
    response = _get_chat_model().invoke(prompt_messages)
    rewritten = str(response.content).strip()
    return rewritten if rewritten else question


def _needs_confirmation(recent_dialogue: str, rewritten_question: str) -> bool:
    prompt_messages = _clarity_prompt_template.format_messages(
        recent_dialogue=recent_dialogue,
        rewritten_question=rewritten_question,
    )
    response = _get_chat_model().invoke(prompt_messages)
    parsed = _safe_json_loads(str(response.content))
    if not parsed:
        return False
    return bool(parsed.get("needs_confirmation", False))


def _resolve_question_or_confirmation(
    conversation_id: str,
    message: str,
    system_prompt: str | None,
) -> tuple[str | None, str | None]:
    with _conversation_lock:
        state = _get_state(conversation_id)
        if system_prompt:
            state.system_prompt = system_prompt

        pending_question = state.pending_rewritten_question
        recent_dialogue = _recent_dialogue_text(state.recent_messages)

        if pending_question and _is_confirmation_text(message):
            state.pending_rewritten_question = None
            return pending_question, None

        if pending_question:
            state.pending_rewritten_question = None

    try:
        rewritten = _rewrite_question(recent_dialogue, message)
        should_confirm = _needs_confirmation(recent_dialogue, rewritten)
    except Exception:
        # Fail-open: if rewrite/clarity step fails, continue with original user question.
        return message, None

    if not should_confirm:
        return rewritten, None

    confirm_text = (
        "为确保我理解正确，请确认你的问题是否是：\n"
        f"{rewritten}\n\n"
        "请回复“确认”继续，或直接补充更明确的问题。"
    )

    with _conversation_lock:
        state = _get_state(conversation_id)
        state.pending_rewritten_question = rewritten

    return None, confirm_text


def _append_user_message(conversation_id: str, message: str) -> None:
    with _conversation_lock:
        state = _get_state(conversation_id)
        state.recent_messages.append(HumanMessage(content=message))
        state.unsummarized_messages.append(HumanMessage(content=message))
        state.recent_messages = state.recent_messages[-MAX_RECENT_MESSAGES:]


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
    _append_user_message(conversation_id, message)

    with _conversation_lock:
        state = _get_state(conversation_id)
        if system_prompt:
            state.system_prompt = system_prompt

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
    rewritten_question, confirm_text = _resolve_question_or_confirmation(
        conversation_id,
        message,
        system_prompt,
    )

    if confirm_text:
        _append_user_message(conversation_id, message)
        _append_ai_message(conversation_id, confirm_text)
        return confirm_text

    question_for_chat = rewritten_question or message
    messages = _prepare_messages(conversation_id, question_for_chat, system_prompt)

    response = _get_chat_model().invoke(messages)
    answer = str(response.content)
    _append_ai_message(conversation_id, answer)
    return answer


def stream_chat_with_openai(
    message: str,
    system_prompt: str | None = None,
    conversation_id: str = "default",
) -> Iterator[str]:
    rewritten_question, confirm_text = _resolve_question_or_confirmation(
        conversation_id,
        message,
        system_prompt,
    )

    if confirm_text:
        _append_user_message(conversation_id, message)
        _append_ai_message(conversation_id, confirm_text)
        yield confirm_text
        return

    question_for_chat = rewritten_question or message
    messages = _prepare_messages(conversation_id, question_for_chat, system_prompt)

    answer_parts: list[str] = []
    for chunk in _get_chat_model().stream(messages):
        text = _chunk_to_text(chunk.content)
        if text:
            answer_parts.append(text)
            yield text
    _append_ai_message(conversation_id, "".join(answer_parts))
