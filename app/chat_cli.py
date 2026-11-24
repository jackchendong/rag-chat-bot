"""直接调用 DeepSeek 的简单多轮命令行对话。"""

import json
import math
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv


TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_system_time",
        "description": "获取运行本程序的计算机当前系统时间，包含本地日期、时间、UTC 偏移和时区。询问现在几点或今天日期时使用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}]


def get_system_time() -> dict[str, str]:
    now = datetime.now().astimezone()
    return {
        "datetime": now.isoformat(timespec="seconds"),
        "timezone": now.tzname() or "",
    }


def execute_tool_call(tool_call: object) -> dict[str, object]:
    if not isinstance(tool_call, dict) or tool_call.get("type") != "function":
        raise ValueError("DeepSeek 返回的工具调用格式不正确。")
    call_id = tool_call.get("id")
    function = tool_call.get("function")
    if not isinstance(call_id, str) or not call_id or not isinstance(function, dict):
        raise ValueError("DeepSeek 返回的工具调用格式不正确。")
    if function.get("name") != "get_system_time":
        raise ValueError("DeepSeek 请求了未支持的工具。")
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        raise ValueError("时间工具的参数必须是 JSON 对象。")
    try:
        parsed = json.loads(arguments)
    except ValueError as error:
        raise ValueError("时间工具的参数不是有效 JSON。") from error
    if not isinstance(parsed, dict) or parsed:
        raise ValueError("时间工具不接受参数，请使用空对象 {}。")
    result = get_system_time()
    print("[工具结果 get_system_time]", flush=True)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False),
    }


def request_deepseek(
    client: httpx.Client, model: str, messages: list[dict[str, object]]
) -> dict[str, object]:
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "thinking": {"type": "disabled"},
        "tools": TOOLS,
    }
    request = client.build_request(
        "POST",
        "chat/completions",
        json=payload,
    )
    # 不输出认证头或 URL 中可能携带凭据的部分。
    log_url = request.url.copy_with(username="", password="", query=None, fragment=None)
    print("\n[HTTP 请求]", flush=True)
    print(
        json.dumps(
            {"method": request.method, "url": str(log_url), "body": payload},
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    response = client.send(request)
    try:
        body = response.json()
    except ValueError:
        body = response.text
    print("[HTTP 响应]", flush=True)
    print(
        json.dumps({"status_code": response.status_code, "body": body},
                   ensure_ascii=False, indent=2),
        flush=True,
    )
    response.raise_for_status()
    try:
        message = body["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ValueError("DeepSeek 返回的数据格式不正确。") from error
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("DeepSeek 返回的消息格式不正确。")
    return message


def ask_deepseek(
    client: httpx.Client, model: str, messages: list[dict[str, object]]
) -> str:
    working = list(messages)
    # 最多执行五轮工具调用，再请求一次最终回复。
    for round_index in range(6):
        message = request_deepseek(client, model, working)
        tool_calls = message.get("tool_calls")
        if tool_calls is None or tool_calls == []:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("DeepSeek 未返回有效的文本回复。")
            messages[:] = working
            return content
        if not isinstance(tool_calls, list) or len(tool_calls) > 8:
            raise ValueError("DeepSeek 返回的工具调用列表无效或过多。")
        if round_index == 5:
            raise ValueError("工具调用轮数达到上限，本轮对话已停止。")
        results = [execute_tool_call(call) for call in tool_calls]
        working.append({
            "role": "assistant",
            "content": message.get("content"),
            "tool_calls": tool_calls,
        })
        working.extend(results)
    raise ValueError("未获得最终回复。")


def main() -> int:
    # 固定读取脚本同目录的 .env，已有环境变量优先。
    load_dotenv(Path(__file__).with_name(".env"), override=False)
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("请在 app/.env 或环境变量中设置 DEEPSEEK_API_KEY。")
        return 1
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
    try:
        url = httpx.URL(base_url)
        timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))
        if url.scheme not in {"http", "https"} or not url.host or not model:
            raise ValueError
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError
    except (ValueError, httpx.InvalidURL):
        print("配置错误：请检查 DeepSeek 地址、模型名和超时秒数（须为正数）。")
        return 1

    messages: list[dict[str, object]] = []
    print("DeepSeek 命令行对话（输入 exit 或 quit 退出，Ctrl+C 也可退出）")
    try:
        with httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        ) as client:
            while True:
                text = input("你：").strip()
                if text.lower() in {"exit", "quit"}:
                    break
                if not text:
                    continue
                pending = messages + [{"role": "user", "content": text}]
                try:
                    reply = ask_deepseek(client, model, pending)
                except httpx.HTTPStatusError as error:
                    print(f"请求失败（HTTP {error.response.status_code}），请检查配置或稍后重试。")
                    continue
                except httpx.RequestError:
                    print("网络请求失败或超时，请检查网络后重试。")
                    continue
                except ValueError as error:
                    print(error)
                    continue
                # 仅将成功完成的一轮对话加入上下文。
                messages = pending + [{"role": "assistant", "content": reply}]
                print(f"DeepSeek：{reply}\n")
    except (EOFError, KeyboardInterrupt):
        print()
    print("对话已结束。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
