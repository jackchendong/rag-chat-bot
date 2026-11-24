# DeepSeek 命令行对话

`chat_cli.py` 使用 Python 3.10+ 直接调用 DeepSeek，支持保留当前进程内的多轮上下文，收到完整回复后一次性输出。退出后不保存历史。

请求固定携带 `"thinking": {"type": "disabled"}` 关闭思考模式，参数说明见 [DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)。

内置 `get_system_time` 工具，无需参数，读取运行脚本的计算机当前本地时间，返回带 UTC 偏移的 ISO 8601 日期时间及系统时区名称。可以输入“现在几点？”或“今天是几月几号？”，由模型决定调用工具；脚本执行后打印格式化的工具结果，并将结果回传给模型生成回答。工具调用过程遵循 [DeepSeek 工具调用文档](https://api-docs.deepseek.com/guides/tool_calls/)，每次 HTTP 请求和响应仍会完整打印。每轮对话最多执行五轮工具调用，每次最多八个调用；无效参数、未知工具或超出上限时显示错误，并保留之前成功的对话历史。

在 `app/` 目录使用 PowerShell：

```powershell
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

若没有虚拟环境，先用 Python 3.10+ 创建 `.venv`。若没有 `.env`，将 `.env.example` 复制为 `.env`，填入自己的 `DEEPSEEK_API_KEY`；已有 `.env` 时只核对所需变量，不要覆盖原文件。

配置项包括 `DEEPSEEK_API_KEY`（必填）、`DEEPSEEK_BASE_URL`（默认 `https://api.deepseek.com`，不含 `/chat/completions`）、`DEEPSEEK_MODEL`（默认 `deepseek-flash`）和 `DEEPSEEK_TIMEOUT_SECONDS`（默认 `60`，正数）。脚本读取同目录 `.env`，环境变量优先。

```powershell
& ./.venv/Scripts/python.exe ./chat_cli.py
```

Git Bash 中去掉命令开头的 `&` 即可。输入问题开始对话，输入 `exit`、`quit` 或按 Ctrl+C 退出；空输入会被忽略。请求失败时显示提示，并且不将失败的一轮加入上下文。

每次调用会在终端打印 `[HTTP 请求]` 和 `[HTTP 响应]`：包括请求方法、地址、完整 JSON 入参、响应状态码和完整响应体。JSON 使用两空格缩进并直接显示中文；错误响应也会打印，非 JSON 响应作为文本显示。网络失败时只有请求日志和失败提示。日志包含本轮发送的全部对话上下文，不打印认证头、URL 用户信息或查询参数，不写入日志文件。

运行时会调用真实 DeepSeek API 并按账户规则计费，不需要启动 Web 服务或连接数据库。接口格式参考 [DeepSeek 多轮对话文档](https://api-docs.deepseek.com/guides/multi_round_chat/)。
