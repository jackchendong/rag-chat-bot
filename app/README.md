# 大模型对话 Demo 后端

基于 FastAPI 的 Python 后端，目前提供 DeepSeek 单轮对话接口，通过 SSE 逐段返回回答。前端不在本次后端目录调整范围内，当前仍是占位页面。

尚未实现：会话历史、知识库/RAG、任务持久化、定时调度、认证及限流。不要把目录规划或技能约定当作已实现功能。

## 运行环境

- Python 3.10，当前本地解释器为 3.10.11。
- 虚拟环境位于 `.venv/`，依赖使用 pip 与 `requirements.txt` 管理。
- FastAPI / Starlette 提供 HTTP 与流式响应，HTTPX 调用模型，python-dotenv 读取 `.env`，Pydantic 校验配置和请求。

以下命令均在本目录 `app/` 中执行。

### 安装与配置

已有 `.venv` 时不需要重新创建。没有时使用 Python 3.10 创建：

```bash
python -m venv .venv
```

Windows Git Bash：

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

新环境中，复制 `.env.example` 为 `.env` 并填写自己的密钥。已有 `.env` 时保留它，不覆盖配置。

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 必填，缺失时启动失败 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com`，必须为无凭据、查询参数和片段的 HTTPS 地址 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash`，可配置为账户支持的模型 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 大于 0 且不超过 600 的有限秒数，默认 60；用于网络读写和连接池等待，连接超时为 10 秒 |

系统环境变量优先于 `.env`。配置在应用启动时读取，不在模块导入时发起网络请求或加载密钥。`.env` 根据模块位置定位到本目录，不依赖终端工作目录；改动配置后重启服务。

该超时不是完整回答总耗时上限。当前每次回答最多 1024 个输出 token，使用非思考模式，不自动重试。

### 启动

Windows Git Bash：

```bash
./.venv/Scripts/python.exe -m uvicorn main:app --reload
```

Windows PowerShell：

```powershell
& ./.venv/Scripts/python.exe -m uvicorn main:app --reload
```

Linux/macOS 使用 `.venv/bin/python` 替换上述 Windows 解释器路径。

默认监听 `http://127.0.0.1:8000`，接口文档位于 `/docs`，OpenAPI 位于 `/openapi.json`。`--reload` 仅用于开发；没有认证与限流，不应直接暴露到公网。

若从仓库根目录启动，使用 Uvicorn 的应用目录参数，不修改 `sys.path`：

```bash
./app/.venv/Scripts/python.exe -m uvicorn main:app --app-dir app --reload
```

`main:app` 是对外启动入口，内部 Python 包名为 `backend`，而不是 `app`。直接导入内部包时在本目录执行；不要混用多个包名导入相同文件。

## 目录与职责

```text
app/
├── main.py                      # 保留的 Uvicorn 入口，仅创建应用
├── backend/
│   ├── application.py           # 应用工厂、路由注册、客户端生命周期与装配
│   ├── api/
│   │   ├── deps.py              # FastAPI Depends 获取应用服务
│   │   ├── responses.py         # SSE 编码、响应头和断连清理
│   │   └── routes/chat.py       # POST /api/chat 路由
│   ├── core/config.py           # .env、环境变量和配置校验
│   ├── schemas/chat.py          # 外部请求字段及校验规则
│   ├── domain/
│   │   ├── chat.py              # 模型增量、回答事件及模型网关 Protocol
│   │   └── errors.py            # 安全的模型服务错误
│   ├── services/chat.py         # 回答流程，生成框架无关的业务事件
│   └── providers/deepseek.py    # DeepSeek HTTP 请求、流解析和错误转换
├── .agents/skills/              # Python 与工程流程技能
├── .vscode/settings.json        # 本目录工作区的解释器和 Git Bash 配置
├── .env.example                 # 可提交的配置模板
├── requirements.txt
├── AGENTS.md
└── README.md
```

各 Python 包包含 `__init__.py`。本地 `.env`、`.venv`、缓存和运行数据不提交。

### 分层边界

```text
请求 → API / Schema → ChatService → ModelGateway → DeepSeekClient → 模型服务
响应 ← SSE 编码     ← ChatEvent   ← ModelChunk   ← 上游流式数据
```

- **API**：处理 HTTP、输入校验、依赖注入与 SSE 传输，不直接调用模型供应商。
- **服务**：面向 `ModelGateway` 协议编排回答，输出普通数据对象，不导入 FastAPI、HTTPX 或供应商实现。
- **领域契约**：使用标准库类型、dataclass 和 Protocol，不依赖 Web、配置或网络层。
- **供应商适配**：负责实际网络请求、供应商数据校验和安全错误转换，不序列化前端 SSE，也不关闭应用拥有的 HTTP 客户端。
- **应用装配**：在 lifespan 内加载配置、创建共享 HTTP 客户端和服务，关闭时回收客户端；导入入口本身不会发送模型请求。

这是适合当前 Demo 的轻量分层，不是完整 DDD 框架。参考 [fastapi-clean-architecture 的 app 结构](https://github.com/keanallen/fastapi-clean-architecture/tree/960f0a861e1024ae5495c3f812e95db238231484/app) 的 API、配置、Schema、Service 分工；没有照搬其用户认证、数据库、全局客户端或异常处理方式。

当前没有数据库，因此不创建空的 `db/`、ORM `models/` 或 `repositories/`。后续引入任务或会话持久化时，再为实际数据访问增加这些职责；模型 HTTP 适配不是数据库 Repository。

## SSE 对话接口

### 请求

`POST /api/chat`，`Content-Type: application/json`：

```json
{"message": "你好，请简单介绍一下自己"}
```

`message` 必须是字符串，去除首尾空白后长度为 1–10000 个字符。拒绝额外字段、空白消息和非字符串值，输入错误返回 HTTP 422。每次只发送当前消息，不保存会话上下文。

Git Bash 调用示例（会调用真实模型并产生费用）：

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请简单介绍一下自己"}'
```

### 事件

返回 `text/event-stream`，每条事件以空行分隔，`data` 是 JSON：

```text
event: message
data: {"content": "你好"}

event: message
data: {"content": "！"}

event: done
data: {"finish_reason": "stop", "truncated": false}

```

- `message`：增量文字，客户端自行拼接；文字中的换行通过 JSON 转义，不破坏 SSE 帧。
- `done`：正常流结束，发送一次；`finish_reason` 为上游结束原因，达到输出上限时 `truncated` 为 `true`。
- `error`：安全错误码与提示，之后结束流，不再发送 `done`。

错误示例：

```text
event: error
data: {"code": "upstream_timeout", "message": "模型服务响应超时，请稍后重试"}

```

错误码包括 `upstream_error`、`upstream_rate_limit`、`upstream_timeout`、`upstream_unavailable`、`invalid_stream` 和 `incomplete_stream`。HTTP 200 只代表 SSE 响应建立，不代表模型回答成功；客户端必须检查终止事件。

POST SSE 不能直接使用浏览器原生 `EventSource` 发送 JSON，应使用 `fetch` 流读取或支持 POST 的 SSE 客户端。反向代理需关闭缓冲并设置合适的读取超时，服务已返回 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。

断连时关闭 SSE 编码器、服务流和供应商流，释放上游连接；取消会继续传播，不转换为普通错误事件。但关闭本地连接不保证供应商已经停止生成或计费。

## 扩展方式

- 新接口：在 `api/routes/` 添加路由，外部字段放 `schemas/`，在 `application.py` 注册。不要为目录分层改变现有 `/api/chat` 为 `/api/v1/chat`。
- 新模型供应商：实现 `ModelGateway.stream_answer`，将供应商输出转为 `ModelChunk`，将可报告的错误转为 `ModelServiceError`，在应用工厂装配；无需修改聊天路由或服务。
- 新业务：先在服务层实现用例，需要共享契约时再增加领域类型；不要把全部规则塞回 `main.py`。
- 持久化与调度：有实际需求后新增存储适配与后台生命周期，明确事务、认领和重启恢复语义，不使用内存列表冒充持久化。

## 验证与安全

当前没有正式测试、lint 或静态类型检查配置。可在本目录运行基础检查：

```bash
./.venv/Scripts/python.exe -m compileall -q main.py backend
./.venv/Scripts/python.exe -m pip check
./.venv/Scripts/python.exe .agents/skills/code-change-verification/scripts/validate_skills.py
```

语法与技能结构检查不代表业务测试通过。接口验证可通过替换 `get_chat_service` 的依赖测试 API；供应商验证可通过 HTTPX MockTransport 模拟字节分块、错误和断连，不默认消耗真实模型余额。替身不能证明真实模型联调通过。

密钥仅放本地 `.env` 或系统环境变量，不写入前端、README、异常响应或日志。不要打印供应商原始错误；在公网使用前补充认证、访问控制、限流与运行监控。
