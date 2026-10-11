# 大模型对话 Demo 后端

基于 FastAPI 的 Python 后端，提供账号登录或创建、用户存在性与会话归属校验、会话历史和 DeepSeek 多轮 SSE 对话。前端已接入，生产文件放在 static/。

尚未实现：知识库/RAG、任务持久化、定时调度、正式认证及限流。当前无密码登录和用户 ID 请求头只适用于 Demo，知道他人账号或 ID 即可冒用，不应处理敏感数据或直接公开部署。

## 运行环境

- Python 3.10，当前本地解释器为 3.10.11。
- 虚拟环境位于 `.venv/`，依赖使用 pip 与 `requirements.txt` 管理。
- FastAPI / Starlette 提供 HTTP 与流式响应，HTTPX 调用模型，python-dotenv 读取 `.env`，Pydantic 校验配置和请求。
- MySQL 使用 SQLAlchemy 2.0 + PyMySQL，数据库版本变更由 Alembic 管理。

以下命令均在本目录 `app/` 中执行。

### 安装与配置

已有 `.venv` 时不需要重新创建。没有时使用 Python 3.10 创建：

```bash
python -m venv .venv
```

Windows Git Bash：

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

新环境中，复制 `.env.example` 为 `.env` 并填写自己的密钥。已有 `.env` 时保留它，不覆盖配置。

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 必填，缺失时启动失败 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com`，必须为无凭据、查询参数和片段的 HTTPS 地址 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash`，可配置为账户支持的模型 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 大于 0 且不超过 600 的有限秒数，默认 60；用于网络读写和连接池等待，连接超时为 10 秒 |
| `MYSQL_HOST` | 必填，MySQL 主机 |
| `MYSQL_PORT` | 默认 3306，范围 1–65535 |
| `MYSQL_USERNAME` | 必填，数据库用户名 |
| `MYSQL_PASSWORD` | 必填，数据库密码，仅保存于本地 `.env` 或环境变量 |
| `MYSQL_DATABASE` | 必填，已有数据库名称；迁移不会创建数据库本身 |

系统环境变量优先于 `.env`。配置在应用启动时读取，不在模块导入时发起网络请求或加载密钥。`.env` 根据模块位置定位到本目录，不依赖终端工作目录；改动配置后重启服务。

该超时不是完整回答总耗时上限。当前每次回答最多 1024 个输出 token，使用非思考模式，不自动重试。

### 启动

Windows Git Bash：

```bash
./.venv/Scripts/python.exe -m uvicorn main:app --reload
python  -m uvicorn main:app --reload
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
│   ├── db/
│   │   ├── base.py              # SQLAlchemy ORM 基类
│   │   └── session.py           # MySQL 引擎与 Session 工厂
│   ├── models/user.py           # 用户表 ORM 映射，不是请求 Schema
│   ├── models/conversation.py   # 会话、用户归属与生成占用标记
│   ├── models/message.py        # 用户消息和助手回答
│   ├── repositories/conversations.py # 同步存储适配、短事务与历史上下文
│   ├── schemas/chat.py          # 外部请求字段及校验规则
│   ├── domain/
│   │   ├── chat.py              # 模型增量、回答事件及模型网关 Protocol
│   │   └── errors.py            # 安全的模型服务错误
│   ├── services/chat.py         # 回答流程，生成框架无关的业务事件
│   └── providers/deepseek.py    # DeepSeek HTTP 请求、流解析和错误转换
├── .agents/skills/              # Python 与工程流程技能
├── .vscode/settings.json        # 本目录工作区的解释器和 Git Bash 配置
├── .env.example                 # 可提交的配置模板
├── static/                      # 前端构建文件，挂载到 /static/
├── alembic.ini                  # 迁移配置，不存储数据库凭据
├── migrations/
│   ├── env.py                   # 在线/离线迁移环境
│   ├── script.py.mako           # 后续 migration 模板
│   └── versions/20261010_0001_create_users.py
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

`db/` 管理数据库连接与 Session，`models/` 定义 ORM 映射，`repositories/` 实现领域存储协议，`migrations/` 记录独立、可审查的数据库变更。服务通过线程池调用同步存储协议，不直接依赖 SQLAlchemy；模型 HTTP 适配不是数据库 Repository。

## 前端静态文件

`app/static/` 用于存放前端构建后的 HTML、JavaScript、CSS 和图片，使用 [FastAPI StaticFiles](https://fastapi.tiangolo.com/tutorial/static-files/) 挂载到 `/static`。目录路径根据后端模块位置解析，从仓库根目录或 `app/` 启动均可使用。

- 将前端构建产物的内容放入本目录，例如 `static/index.html` 和 `static/assets/`；不要把整个 `dist` 文件夹再嵌套一层。
- 放入 `index.html` 后，访问 `http://127.0.0.1:8000/static/` 打开页面；资源路径为 `/static/assets/...`。
- 前端构建使用 `/static/` base。在 front/ 执行 `pnpm build:backend` 可将页面和资源直接构建到本目录，保留 `.gitkeep`，不自动清空外部输出目录。
- 未构建页面时 `/static/` 返回 404；缺失资源同样返回 404，不自动回退到首页。当前页面使用组件状态切换而非 history 路由。
- 静态路由不影响 `/api/chat`、`/docs` 和 `/openapi.json`，也不新增根路径 `/` 的页面。
- 构建产物被 Git 忽略，仅保留 `.gitkeep`。本目录中的文件可被公开访问，不能放入 `.env`、数据库配置、密钥或用户私有数据。

## MySQL 与手动迁移

已提供两份 migration，开发过程**未连接远程数据库或执行在线迁移**。现有 app/.env 保留 DeepSeek 和 MySQL 配置，该文件被 Git 忽略。迁移独立加载 MySQL 配置，不要求 DeepSeek 密钥。

第二份 `20261010_0002_conversations.py` 增加 account 唯一约束及 conversations、messages 两张表、外键和查询索引。账号依照现有 utf8mb4_unicode_ci 排序规则比较，不区分大小写；已存在重复账号时迁移会失败，需人工确认处理，不自动删除用户或合并历史。MySQL DDL 不保证整份迁移原子回滚，失败后需检查结构，不直接盲目重试。

conversations 使用 UUID 字符串主键、user_id、title、内部 active_message_id 和时间字段；messages 使用 BIGINT 主键、conversation_id、role、content、status 和时间字段。接口 ID 均为字符串，日期为 UTC ISO 8601。回退第二份迁移会删除全部会话和消息，需提前备份。

迁移创建 `users` 表，业务字段只有以下四个：

| 字段 | 类型与规则 |
|---|---|
| `id` | `BIGINT UNSIGNED`，自增主键 |
| `account` | `VARCHAR(255)`，非空，第二份迁移添加唯一约束 |
| `created_at` | `DATETIME(6)`，非空，插入时由数据库生成 |
| `updated_at` | `DATETIME(6)`，非空，插入时生成，数据实际变更时由数据库自动更新 |

表使用 InnoDB、utf8mb4 和 utf8mb4_unicode_ci。应用和在线迁移的连接初始化时将会话时区设为 UTC；DATETIME 本身不带时区，读取后按 UTC 解释。其他客户端写入时也需要保持 UTC 会话时区。时间默认值和自动更新按 [SQLAlchemy MySQL 文档](https://docs.sqlalchemy.org/en/20/dialects/mysql.html#rendering-on-update-current-timestamp-for-mysql-mariadb-s-explicit-defaults-for-timestamp) 显式声明。

先确认目标 `chat` 数据库已存在、连接账号有建表权限，并安装 `requirements.txt`。以下命令在 `app/` 中由你手动执行：

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```

Alembic 同时维护自己的 `alembic_version` 版本表。已存在 `users` 时不要直接执行首个迁移，应先检查现有结构和迁移基线；不要用 `stamp` 冒充已完成建表。

只查看迁移文件版本（不连接数据库）：

```bash
./.venv/Scripts/python.exe -m alembic heads
./.venv/Scripts/python.exe -m alembic history
```

只生成 SQL 供审查、不连接数据库（[Alembic 离线模式](https://alembic.sqlalchemy.org/en/latest/offline.html)）：

```bash
./.venv/Scripts/python.exe -m alembic upgrade head --sql
```

离线 SQL 不包含真实连接凭据。未来修改 ORM 后，可以手动使用 `alembic revision --autogenerate -m "describe_change"` 生成候选变更；**autogenerate 会连接数据库**，必须人工检查后再执行升级。首个 migration 的 `downgrade` 会删除整个用户表及数据，回退前需备份。

启动服务仅创建惰性连接池，不连接数据库、不调用 create_all、不自动迁移；登录、历史和聊天请求才实际访问数据库。存储适配每次操作使用独立 Session 和短事务，生成流期间不占用数据库事务。数据库连接、读取和写入超时均为 10 秒。同步路由由 FastAPI 在线程池执行，异步聊天通过 AnyIO 线程池调用存储。生产环境应换用最小权限账号并配置加密连接。

## 登录与历史接口

| 接口 | 说明 |
|---|---|
| POST /api/login | JSON `{"account":"alice"}`，去除首尾空格，1–255 字符；存在则查询，不存在则创建，返回 user_id 和 account |
| GET /api/users/me | 校验用户并返回当前账号 |
| POST /api/conversations | 创建会话，返回 conversation_id、title、updated_at |
| GET /api/conversations | 当前用户会话，updated_at 倒序；offset 默认 0、limit 默认 30，最多 100 |
| GET /api/conversations/{conversation_id}/messages | 消息按 ID 升序返回，默认最近 50 条、最多 100；before 为最早消息 ID，可分页读取更早记录 |

除登录外，均需 `X-User-Id` 请求头。缺失、非法或不存在的用户返回 401；会话不存在或不属于用户返回 404；同一会话正在生成返回 409；数据库失败返回脱敏的 503。HTTP 错误使用 `{"code":"...","message":"..."}`，输入格式错误为 422。

退出没有后端接口，前端取消请求、删除 localStorage 中的 account 和 user_id，不删除用户及历史。刷新时请求 users/me，用户不存在时清除状态，网络失败时保留状态并提供重试。

## SSE 对话接口

### 请求

`POST /api/chat`，`Content-Type: application/json`，请求头 `X-User-Id` 必填：

```json
{"conversation_id":"替换为创建会话接口返回的 UUID","message":"你好，请简单介绍一下自己"}
```

message 去除首尾空白后为 1–10000 字符，conversation_id 必须是 UUID，拒绝额外字段和非字符串消息。用户与归属校验在 SSE 建立前完成。前端只发送当前消息，后端从数据库最近 40 条记录中提取成功的完整轮次，最多保留含当前消息的 30000 字符上下文，不包含失败或取消的轮次；历史展示仍保留这些记录。

Git Bash 调用示例（会调用真实模型并产生费用）：

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'X-User-Id: 替换为登录返回的用户ID' \
  -d '{"conversation_id":"替换为创建会话返回的UUID","message":"你好，请简单介绍一下自己"}'
```

### 事件

返回 `text/event-stream`，每条事件以空行分隔，`data` 是 JSON：

```text
event: meta
data: {"conversation_id":"会话UUID","user_message_id":"1","assistant_message_id":"2"}

event: message
data: {"content": "你好"}

event: message
data: {"content": "！"}

event: done
data: {"finish_reason": "stop", "truncated": false}

```

- `meta`：已保存用户消息与助手占位记录，返回会话和消息 ID。
- `message`：增量文字，客户端自行拼接；文字中的换行通过 JSON 转义，不破坏 SSE 帧。
- `done`：回答全文已经提交数据库后发送一次；finish_reason 为上游结束原因，达到输出上限时 truncated 为 true。
- `error`：安全错误码与提示，之后结束流，不再发送 `done`。

错误示例：

```text
event: error
data: {"code": "upstream_timeout", "message": "模型服务响应超时，请稍后重试"}

```

错误码包括 `upstream_error`、`upstream_rate_limit`、`upstream_timeout`、`upstream_unavailable`、`invalid_stream` 和 `incomplete_stream`。HTTP 200 只代表 SSE 响应建立，不代表模型回答成功；客户端必须检查终止事件。

POST SSE 不能直接使用浏览器原生 `EventSource` 发送 JSON，应使用 `fetch` 流读取或支持 POST 的 SSE 客户端。反向代理需关闭缓冲并设置合适的读取超时，服务已返回 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。

断连时关闭 SSE 编码器、服务流和供应商流，释放上游连接；取消会继续传播，不转换为普通错误事件。但关闭本地连接不保证供应商已经停止生成或计费。

消息状态为 generating、completed、failed 或 cancelled；停止和失败保留已生成的部分文本。完整生成总预算为 120 秒，回答存储限制为 60000 UTF-8 字节。生成前通过会话行锁提交 active_message_id，避免多个进程同时回复同一会话；进程异常退出遗留的占用在下一次请求时，超过 5 分钟才标记失败并释放。异常退出前未最终保存的增量不会恢复，不宣称支持断点续传。

## 扩展方式

- 新接口：在 `api/routes/` 添加路由，外部字段放 `schemas/`，在 `application.py` 注册。不要为目录分层改变现有 `/api/chat` 为 `/api/v1/chat`。
- 新模型供应商：实现 `ModelGateway.stream_answer`，将供应商输出转为 `ModelChunk`，将可报告的错误转为 `ModelServiceError`，在应用工厂装配；无需修改聊天路由或服务。
- 新业务：先在服务层实现用例，需要共享契约时再增加领域类型；不要把全部规则塞回 `main.py`。
- 持久化与调度：有实际需求后新增存储适配与后台生命周期，明确事务、认领和重启恢复语义，不使用内存列表冒充持久化。

## 验证与安全

### DeepSeek 请求日志

应用启动时为 backend 日志配置 INFO 级别控制台输出，不修改全局或 HTTPX 日志级别。每次请求 DeepSeek 前仅记录实际发送的 JSON payload：model、完整 messages（role 与 content，包含实际发送的历史上下文）、stream、max_tokens 和 thinking。不额外记录请求 ID、方法、地址、请求头、消息数量或响应状态码；保留标准日志前缀。

payload 不包含 Authorization 或数据库配置，因此不会直接打印配置中的 API key 或数据库密码。完整消息日志按用户要求启用，消息内的个人信息或用户自行输入的秘密也会原样输出，仅用于本地调试；分享日志前务必检查并脱敏。不记录响应正文，日志不改变请求内容和 SSE 协议，不单独发起模型调用；默认输出到控制台，不自动写入文件。

当前没有正式测试、lint 或静态类型检查配置。可在本目录运行基础检查：

```bash
./.venv/Scripts/python.exe -m compileall -q main.py backend migrations
./.venv/Scripts/python.exe -m pip check
./.venv/Scripts/python.exe .agents/skills/code-change-verification/scripts/validate_skills.py
```

语法与技能结构检查不代表业务测试通过。接口验证可通过替换 `get_chat_service` 的依赖测试 API；供应商验证可通过 HTTPX MockTransport 模拟字节分块、错误和断连，不默认消耗真实模型余额。替身不能证明真实模型联调通过。

密钥仅放本地 `.env` 或系统环境变量，不写入前端、README、异常响应或日志。不要打印供应商原始错误；在公网使用前补充认证、访问控制、限流与运行监控。
