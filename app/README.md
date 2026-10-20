# 大模型对话 Demo 后端

基于 FastAPI 的 Python 后端，提供账号登录或创建、用户存在性与会话归属校验、会话历史和 DeepSeek 多轮 SSE 对话。前端已接入，生产文件放在 static/。

已实现 function calling、Skills、Agent loop、联网和受限 Shell 工具、执行任务与步骤审计，以及 AI 对话创建的 APScheduler + MySQL 持久化定时任务。尚未实现：知识库/RAG、正式认证及限流。当前无密码登录和用户 ID 请求头只适用于 Demo，知道他人账号或 ID 即可冒用，不应处理敏感数据或直接公开部署。

## 运行环境

- Python 3.10，当前本地解释器为 3.10.11。
- 虚拟环境位于 `.venv/`，依赖使用 pip 与 `requirements.txt` 管理。
- FastAPI / Starlette 提供 HTTP 与流式响应，HTTPX 调用模型，python-dotenv 读取 `.env`，Pydantic 校验配置和请求。
- MySQL 8.0+ 使用 SQLAlchemy 2.0 + PyMySQL，数据库版本变更由 Alembic 管理；调度认领使用 InnoDB 行锁和 SKIP LOCKED。

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

该超时不是完整回答总耗时上限。当前每轮模型调用最多 1024 个输出 token，使用非思考模式，不自动重试。

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

默认监听 `http://127.0.0.1:8000`，接口文档位于 `/docs`，ReDoc 位于 `/api/redoc`，OpenAPI 位于 `/api/openapi.json`。`--reload` 仅用于开发；没有认证与限流，不应直接暴露到公网。

若从仓库根目录启动，使用 Uvicorn 的应用目录参数，不修改 `sys.path`：

```bash
./app/.venv/Scripts/python.exe -m uvicorn main:app --app-dir app --reload
```

`main:app` 是对外启动入口，内部 Python 包名为 `backend`，而不是 `app`。直接导入内部包时在本目录执行；不要混用多个包名导入相同文件。

## Docker 部署

Dockerfile 和构建忽略文件分别位于 `app/Dockerfile`、`app/Dockerfile.dockerignore`。镜像仅安装 Python 后端依赖，pip 使用清华 PyPI 镜像源 `https://pypi.tuna.tsinghua.edu.cn/simple`；直接复制本地已打包的 `app/static/`，由 FastAPI 提供 API 和静态页面。Docker 构建不安装 Node.js，也不编译前端。镜像内使用 Python 3.10，默认以 root 运行单个 Uvicorn worker，不使用开发热重载。

先在本地 front 目录执行 `pnpm build`，生成 app/static/index.html 和资源文件，再将 app 目录连同 static 上传服务器。static 构建产物被 Git 忽略，仅拉取代码不会得到页面文件。镜像构建会检查 static/index.html，未打包或未上传时直接失败。

**以下命令在服务器的 app 目录执行**，构建上下文只需该目录：

```bash
docker build -t rag-chat-bot:latest .
```

从仓库根目录执行时使用 `docker build -f app/Dockerfile -t rag-chat-bot:latest app`。Dockerfile 专属忽略文件允许后端源码、Skills、static 产物和本地 `.env` 进入构建，迁移文件、虚拟环境、node_modules、缓存、测试和运行数据被排除。该文件命名与优先级遵循 [Docker 构建上下文说明](https://docs.docker.com/build/concepts/context/#dockerignore-files)。

构建前在 app 目录准备 `.env`（可参考 `.env.example`，不要提交真实凭据），构建时直接复制为镜像内的 `/app/.env`，配置变更后需重新构建，或通过运行时环境变量覆盖。该文件会包含在镜像中。容器内的 127.0.0.1 指向容器自身，MYSQL_HOST 要填写容器能够访问的 MySQL 8.0+ 地址；MySQL 在宿主机时可填写 host.docker.internal，下面的命令通过 host-gateway 为其添加映射。MySQL 在同一 Docker 网络中时，使用其容器服务名，并为下述运行命令添加 `--network 网络名`。

容器安装系统 tzdata，并将 TZ、/etc/localtime 和 /etc/timezone 统一设为中国时区 Asia/Shanghai。数据库仍按应用约定存储 UTC，定时计划继续使用各任务保存的 IANA 时区。

这是 Demo 部署，数据库结构由你在本地提前准备。镜像构建和容器启动均不执行 migration，服务器直接启动服务：

```bash
docker run -d --name rag-chat-bot --restart unless-stopped \
  --stop-timeout 60 \
  --add-host host.docker.internal:host-gateway \
  -p 127.0.0.1:8000:8000 \
  rag-chat-bot:latest

docker logs --tail 100 -f rag-chat-bot
```

以上多行命令使用 Linux/Bash 的续行方式。PowerShell 中可将每条命令合并为一行。默认端口仅映射服务器本机，访问 `http://127.0.0.1:8000/` 即为聊天页面，`/docs` 为接口文档；对外访问可接现有反向代理。Nginx 代理 SSE 时配置 `proxy_buffering off` 和足够的 `proxy_read_timeout`（例如 300s）。如果确需直接开放端口，将映射改为 `-p 8000:8000`；项目仍为无密码 Demo 身份识别。

任务、执行记录和会话均保存在外部 MySQL 中，重建容器不会清除它们；数据库需要持续可用。运行时 Skills 已包含在镜像中，Shell 的默认工作目录 `/app/workspace` 可由容器用户写入。更新代码后重新构建镜像，并停止、移除旧容器后用上述参数重新创建；不要用 `--reload` 或额外添加多个 worker。60 秒停止宽限用于等待后台任务取消和结果保存。默认读取镜像内 `.env`，也可在 docker run 中增加 `--env-file .env`，以环境变量覆盖镜像内同名配置。

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
│   │   ├── chat.py              # 模型增量、回答事件及模型网关抽象基类
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
- **服务**：面向 `ModelGateway` 抽象基类编排回答，输出普通数据对象，不导入 FastAPI、HTTPX 或供应商实现。
- **领域契约**：使用标准库类型、dataclass、`ABC` 和 `@abstractmethod`，不依赖 Web、配置或网络层。`DeepSeekClient(ModelGateway)` 和 `ConversationRepository(ConversationStore)` 显式继承领域抽象基类；缺少抽象方法实现的子类不能实例化。
- **供应商适配**：负责实际网络请求、供应商数据校验和安全错误转换，不序列化前端 SSE，也不关闭应用拥有的 HTTP 客户端。
- **应用装配**：在 lifespan 内加载配置、创建共享 HTTP 客户端和服务，关闭时回收客户端；导入入口本身不会发送模型请求。

这是适合当前 Demo 的轻量分层，不是完整 DDD 框架。参考 [fastapi-clean-architecture 的 app 结构](https://github.com/keanallen/fastapi-clean-architecture/tree/960f0a861e1024ae5495c3f812e95db238231484/app) 的 API、配置、Schema、Service 分工；没有照搬其用户认证、数据库、全局客户端或异常处理方式。

`db/` 管理数据库连接与 Session，`models/` 定义 ORM 映射，`repositories/` 显式继承并实现领域存储抽象基类，`migrations/` 记录独立、可审查的数据库变更。服务通过线程池调用同步存储方法，不直接依赖 SQLAlchemy；模型 HTTP 适配不是数据库 Repository。

## 前端静态文件

`app/static/` 用于存放前端构建后的 HTML、JavaScript、CSS 和图片，使用 [FastAPI StaticFiles](https://fastapi.tiangolo.com/tutorial/static-files/) 挂载到 `/static`。目录路径根据后端模块位置解析，从仓库根目录或 `app/` 启动均可使用。

- 将前端构建产物的内容放入本目录，例如 `static/index.html` 和 `static/assets/`；不要把整个 `dist` 文件夹再嵌套一层。
- 放入 `index.html` 后，访问 `http://127.0.0.1:8000/static/` 打开页面；资源路径为 `/static/assets/...`。
- 前端构建使用 `/static/` base。在 `front/` 执行 `pnpm build` 可将页面和资源直接构建到本目录；`pnpm build:backend` 是同一命令的别名。构建保留 `.gitkeep`，不自动清空输出目录。
- 未构建页面时 `/static/` 返回 404；缺失资源同样返回 404，不自动回退到首页。当前页面使用组件状态切换而非 history 路由。
- 非 `/api`、`/docs` 开头且不在 `/static/` 下的路径（包括 `/`）返回 HTTP 307，重定向到 `/static/index.html`。`/static/` 下继续直接提供页面和资源，避免重定向循环；缺失资源保持 404。
- `/api`、`/docs` 开头的请求保留路由行为，未知路径返回 404。接口文档保留在 `/docs`，使用 `/api/openapi.json` 加载接口定义；旧 `/openapi.json` 路径会重定向到前端入口。
- 构建产物被 Git 忽略，仅保留 `.gitkeep`。本目录中的文件可被公开访问，不能放入 `.env`、数据库配置、密钥或用户私有数据。

## MySQL 与手动迁移

已提供三份 migration（最新版本 `20261011_0003` 新增 Agent 审计表），开发过程**未连接远程数据库或执行在线迁移**。现有 app/.env 保留 DeepSeek 和 MySQL 配置，该文件被 Git 忽略。迁移独立加载 MySQL 配置，不要求 DeepSeek 密钥。

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
| POST /api/chat/stop | 精确停止指定助手回答，校验用户与会话归属，详见下文 |

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
data: {"finish_reason": "stop", "truncated": false, "cancelled": false}

```

- `meta`：已保存用户消息与助手占位记录，返回会话、消息 ID 和 Agent `task_id`。
- `message`：增量文字，客户端自行拼接；文字中的换行通过 JSON 转义，不破坏 SSE 帧。
- `done`：回答内容和最终状态已经提交数据库后发送一次；正常结束时 finish_reason 为上游结束原因，达到输出上限时 truncated 为 true。主动停止时 cancelled 为 true、finish_reason 为 cancelled，保存部分内容而非完整回答。
- `error`：安全错误码与提示，之后结束流，不再发送 `done`。

错误示例：

```text
event: error
data: {"code": "upstream_timeout", "message": "模型服务响应超时，请稍后重试"}

```

错误码包括 `upstream_error`、`upstream_rate_limit`、`upstream_timeout`、`upstream_unavailable`、`invalid_stream` 和 `incomplete_stream`。HTTP 200 只代表 SSE 响应建立，不代表模型回答成功；客户端必须检查终止事件。

POST SSE 不能直接使用浏览器原生 `EventSource` 发送 JSON，应使用 `fetch` 流读取或支持 POST 的 SSE 客户端。反向代理需关闭缓冲并设置合适的读取超时，服务已返回 `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`。

断连时关闭 SSE 编码器、服务流和供应商流，释放上游连接；取消会继续传播，不转换为普通错误事件。但关闭本地连接不保证供应商已经停止生成或计费。

### 停止生成

`POST /api/chat/stop`，请求头同样需要 `X-User-Id`：

```json
{"conversation_id":"替换为会话UUID","assistant_message_id":"替换为meta事件中的助手消息ID"}
```

`assistant_message_id` 是正整数字符串，最大值为 18446744073709551615。通过消息 ID 定位本轮，防止迟到的停止请求误停后续回答。会话不属于当前用户、消息不属于该会话或消息不是助手回答时返回 404；输入不合法返回 422。

响应为 `{"stopped":true}`，表示已将目标回答标记为 cancelled；重复停止同一条已取消回答仍返回 true。回答已经正常完成或失败时返回 `{"stopped":false}`，不修改已有内容和状态。

停止标记使用现有消息状态保存到数据库，不需要新增迁移，不依赖进程内任务表。生成服务在等待模型片段和工具执行时按 `AGENT_STOP_POLL_SECONDS` 检查状态（默认 250 毫秒）（实际延迟还包括数据库操作耗时），检测停止后取消等待、关闭模型流、保存已生成内容，并发送：

```text
event: done
data: {"finish_reason":"cancelled","truncated":false,"cancelled":true}

```

停止接口成功表示标记已保存；上述 SSE 结束事件表示部分文本已最终保存、模型流已关闭。前端在收到 `meta` 后启用“停止生成”，点击时调用接口并显示“正在停止…”，继续读取 SSE 直到终止确认。停止请求失败时保留当前流并允许重试。切换会话、退出和卸载仍通过断连关闭当前请求。

停止与正常完成同时发生时，以数据库事务提交顺序确定最终状态；已标记取消的回答不会再被改回 completed。新一轮开始后，旧流的清理也不会清除新一轮的占用标记。

消息状态为 generating、completed、failed 或 cancelled；停止和失败保留已生成的部分文本。完整 Agent 执行总预算由 `AGENT_TIMEOUT_SECONDS` 控制，默认 120 秒，回答存储限制为 60000 UTF-8 字节。生成前通过会话行锁提交 active_message_id，避免多个进程同时回复同一会话；进程异常退出遗留的占用在下一次请求时，超过 5 分钟才标记失败并释放。异常退出前未最终保存的增量不会恢复，不宣称支持断点续传。

## 扩展方式

- 新接口：在 `api/routes/` 添加路由，外部字段放 `schemas/`，在 `application.py` 注册。不要为目录分层改变现有 `/api/chat` 为 `/api/v1/chat`。
- 新模型供应商：显式继承 `ModelGateway` 并实现 `stream_answer`，将供应商输出转为 `ModelChunk`，将可报告的错误转为 `ModelServiceError`，在应用工厂装配；无需修改聊天路由或服务。测试替身也应显式继承对应抽象基类并实现所需抽象方法。
- 新业务：先在服务层实现用例，需要共享契约时再增加领域类型；不要把全部规则塞回 `main.py`。
- 持久化与调度：有实际需求后新增存储适配与后台生命周期，明确事务、认领和重启恢复语义，不使用内存列表冒充持久化。

## 验证与安全

### DeepSeek 请求日志

应用启动时为 backend 日志配置 INFO 级别控制台输出，不修改全局或 HTTPX 日志级别。每次请求 DeepSeek 前仅记录实际发送的 JSON payload：model、完整 messages（含系统指令、实际历史、tool_calls 和工具结果）、stream、max_tokens、thinking 以及可用 tools/tool_choice。不额外记录请求 ID、方法、地址、请求头、消息数量或响应状态码；保留标准日志前缀。

payload 不包含 Authorization 或数据库配置，因此不会直接打印配置中的 API key 或数据库密码。完整消息日志按用户要求启用，消息内的个人信息或用户自行输入的秘密也会原样输出，仅用于本地调试；分享日志前务必检查并脱敏。不记录响应正文，日志不改变请求内容和 SSE 协议，不单独发起模型调用；默认输出到控制台，不自动写入文件。

当前使用标准库 unittest 验证 Agent loop、SSE/API、停止与断连、工具超时、Shell 子进程回收、上游分片解析和审计归属，没有额外测试框架、lint 或静态类型检查配置。测试使用隔离的临时 SQLite 数据库和模型替身，不连接实际 MySQL、不调用真实模型；不验证 MySQL 行锁行为。可在本目录运行：

```bash
./.venv/Scripts/python.exe -m unittest discover -s tests -v
./.venv/Scripts/python.exe -m compileall -q main.py backend migrations tests
./.venv/Scripts/python.exe -m pip check
./.venv/Scripts/python.exe .agents/skills/code-change-verification/scripts/validate_skills.py
```

语法与技能结构检查不代表业务测试通过。接口验证可通过替换 `get_chat_service` 的依赖测试 API；供应商验证可通过 HTTPX MockTransport 模拟字节分块、错误和断连，不默认消耗真实模型余额。替身不能证明真实模型联调通过。本次验证采用本地测试与自查，未进行独立代码审查。

密钥仅放本地 `.env` 或系统环境变量，不写入前端、README、异常响应或日志。不要打印供应商原始错误；在公网使用前补充认证、访问控制、限流与运行监控。


## Function calling、Skills 与 Agent loop

实现参考 [Open WebUI 的工具循环](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/utils/middleware.py) 与 [Skills 数据模型](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/models/skills.py)，采用本项目的显式 ABC 继承、短事务和 POST SSE；没有引入 Open WebUI 的动态 Python 工具执行器或数据库管理界面。模型协议采用 [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)。

流程：`/api/chat → ChatService.prepare → 保存消息与 agent_tasks → ChatService.answer → DeepSeekClient.stream_answer → 聚合 tool_calls 分片 → 保存 agent_task_steps → ToolRegistry.execute → 添加 assistant.tool_calls 与 role=tool/tool_call_id → 下一轮模型 → 保存最终消息与任务 → done`。

- 只有完整上游 `[DONE]` 且 finish_reason 为 tool_calls 时才执行工具。工具参数由 JSON 与 Pydantic 校验，不执行模型生成的代码。
- 每轮可包含多项工具调用，按顺序执行；不会自动重试工具。重复 tool_call_id 会终止任务，避免重复副作用。
- 默认最多 6 轮模型、12 次工具调用；最后一轮不提供工具，留给模型生成最终回答。到达预算、上下文超长或总超时会保存部分回答并发送 error。工具自身的参数错误、禁用、未配置或超时记为 failed，并作为工具结果交回模型，由模型解释或调整。
- `meta` 增加 task_id；工具开始和结束时增加 `agent_step` 事件，字段为 task_id、step_id、name、status。既有前端忽略额外事件，继续展示 message 和 done/error；工具调用与循环无需新增前端操作。审计查询当前通过 API 或 /docs 使用。
- stop 与断连取消当前模型读取或联网 HTTP 请求；POSIX 下 Shell 杀死整个进程组并回收子进程。取消后保存部分回答和步骤状态，不能保证外部服务停止计费，已完成的工具不会回滚。

### 联网工具

`web_search(query, max_results=5, topic="general", time_range?)` 与 `web_read(url)` 保持统一工具名称，底层供应商由 `AGENT_WEB_PROVIDER` 控制：

- `auto`（默认）：有 TAVILY_API_KEY 时使用 [Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search) / [Extract](https://docs.tavily.com/documentation/api-reference/endpoint/extract)，没有密钥时自动使用公开搜索与直接网页读取。
- `public`：固定使用免密钥方案。通用查询使用搜狗；`topic="news"` 使用 Google News RSS，`time_range="day"` / `week` / `month` 限定新闻查询窗口。公开入口可能限流、返回验证码或不可达；失败会返回实际错误，不能保证始终可用。通用搜索的时间窗口请同时写进 query，并核对原文日期。
- `tavily`：固定使用 Tavily，缺少密钥才返回 tool_not_configured。更改配置后重启服务。

每次搜索最多 5 条结果，附来源链接、发布时间（供应商提供时）及抓取时间。公开新闻 RSS 的日期来自新闻源，内容是搜索摘要，链接可能是聚合页；总结全文前应按标题搜索原始报道并调用 web_read。只获取到摘要时明确说明依据，不能拿标题编造全文。系统指令与 web-research Skill 要求核对“今天”的实际发布日期；不足 3 篇时不凑数。

公开模式 web_read 只支持 HTML/纯文本，去除脚本等内容，响应上限 1MB、正文最多 8000 字符、最多 4 次请求（含重定向）。每个目标及重定向都校验 DNS 公网地址，再固定 IP 请求并保留 Host 与 TLS SNI，拒绝内网、localhost、凭据、非标准端口及非 HTTP/HTTPS 地址，不继承环境代理、Cookie 或认证信息。若本机代理仅返回 198.18.0.0/15 虚拟 DNS 地址，通过固定 [Google DoH](https://developers.google.com/speed/public-dns/docs/doh/json) 入口查询真实 A 记录，仍须全部通过公网校验；不直接访问虚拟地址。需要服务器能直连这些公网服务；仅能通过环境 HTTP 代理联网的部署可能读取失败。Tavily 模式则由供应商远程抓取正文。

网页需要登录、验证码或 JavaScript 时可能读不到正文，工具会报告失败。网页内容始终是不可信资料。天气优先用独立 get_weather；没有城市时先询问，用户补充城市后结合历史继续查询，不因 Tavily 密钥为空拒绝天气或公开搜索。

### Shell 工具

`shell_exec({"argv":["ls","-la"]})` 在 AGENT_SHELL_WORKSPACE 固定目录执行 argv。实际使用 create_subprocess_exec，无 shell=True；没有管道、重定向、解释器、任意脚本或自定义 cwd。当前白名单仅支持 pwd、ls、date、echo、uname、whoami，各命令还有参数校验；ls 只能列出工作目录本身，不能读取目录外文件。可以用 AGENT_SHELL_ALLOWLIST 缩小白名单，用 AGENT_SHELL_ENABLED=false 禁用。

子进程不继承模型、数据库和联网密钥，stdout+stderr 合计有字节上限，超时/停止会回收进程。在 Linux/macOS 使用系统程序；Windows 缺少对应程序会返回 command_missing，不会改用 cmd.exe。这是受限命令执行器，**不是操作系统沙箱**，暂不支持通用脚本或读写项目代码。app/workspace 是被 Git 忽略的本地运行目录，管理员不要配置为含秘密的目录。

### Skills

运行时 Skills 位于 `app/skills/<name>/SKILL.md`，与用于开发 Codex 的 `app/.agents/skills` 不同。文件使用 YAML frontmatter，name 必须与目录名一致，description 为非空字符串；名称仅小写字母、数字与连字符。启动时验证，目录最多 32 项，每文件最多 32000 字节，拒绝目录逃逸和指向目录外的符号链接。

默认仅把名称、说明和 hash 放进系统上下文，模型通过 load_skill(name) 加载完整内容。也可在聊天请求加入 `"skill_names":["web-research"]` 预加载（最多 8 个）。内置 web-research 和 shell-inspection。Skill 仅提供指令，不执行脚本，不会自动注册工具，也不会绕过 Shell/联网权限；新增文件后建议重启服务。

管理员维护受信任的 Skill 文件；接口不提供上传/写入或模型修改。任务快照记录所选 Skill 的内容与 SHA256，按需加载的内容与 hash 保存在工具步骤输出中；超过模型工具结果预算时，模型仅接收截断预览；审计输出仍保留工具实际返回的有界完整结果（result）和模型实际接收的结果（model_result）。网页自身在抓取适配时的正文上限仍适用，不保留整站原文。

### 配置

app/.env 和可提交的 .env.example 均已增加注释。相对目录以 app 为基准，环境变量仍优先。

| 配置 | 默认值与含义 |
|---|---|
| AGENT_ENABLED | true；false 关闭工具和循环，普通回答仍保留审计 |
| AGENT_MAX_ROUNDS / AGENT_MAX_TOOL_CALLS | 6 / 12；每个回答的模型与工具次数预算 |
| AGENT_TIMEOUT_SECONDS | 120；整个执行总预算，最大 240 秒 |
| AGENT_TOOL_TIMEOUT_SECONDS | 20；每个工具上限，最大 60 秒 |
| AGENT_STOP_POLL_SECONDS | 0.25；停止标记检查间隔，另有数据库访问耗时 |
| AGENT_MAX_CONTEXT_CHARS | 60000；含系统指令、JSON 消息和工具定义，超过预算终止 |
| AGENT_MAX_TOOL_OUTPUT_CHARS | 12000；超长工具结果返回有效 JSON 截断预览 |
| AGENT_SKILLS_DIR | ./skills；管理员维护的 SKILL.md 目录 |
| AGENT_WEATHER_ENABLED | true；注册免密钥天气工具，独立于 Tavily |
| AGENT_WEB_ENABLED | true；注册通用搜索与网页读取工具 |
| AGENT_WEB_PROVIDER | auto；有密钥用 Tavily，无密钥用公开搜索；也可指定 public / tavily |
| TAVILY_API_KEY | 空；可选，固定 tavily 模式必须填写 |
| AGENT_SHELL_ENABLED | true；是否注册受限命令工具 |
| AGENT_SHELL_WORKSPACE | ./workspace；固定命令工作目录 |
| AGENT_SHELL_ALLOWLIST | pwd,ls,date,echo,uname,whoami；仅能缩小受支持程序集 |

### 审计表与查询

| 表 | 主要字段与关联 |
|---|---|
| agent_tasks | UUID id、user_id、conversation_id、user_message_id、唯一 assistant_message_id；status、model、input_text/output_text、settings_snapshot、round_count/tool_call_count、error、started_at/finished_at、created_at/updated_at |
| agent_task_steps | 自增 id、task_id、step_no、round_no、kind(model/tool)、name、tool_call_id；status、input_data/output_data、started_at/finished_at、duration_ms、created_at/updated_at |

任务与步骤使用 running/completed/failed/cancelled 状态；task_id+step_no 与 task_id+tool_call_id 唯一，消息/用户/会话/任务均有外键。模型步骤保存实际请求消息和工具定义、可见响应及工具调用；工具步骤先写入 running 再执行，保存参数、结果或安全错误。快照不含 API key 或数据库连接凭据；输入、输出和网页内容可能含私人信息，审计不是脱敏存储。

- GET /api/skills：可用 Skill 摘要与工具定义。
- GET /api/agent/tasks?conversation_id=UUID&offset=0&limit=20：当前用户任务摘要；conversation_id 可省略。
- GET /api/agent/tasks/{task_id}?offset=0&limit=20：任务详情及分页步骤，按 step_no 排序。

均要求已有用户的 X-User-Id，任务只能由对应用户查询，其他用户查询详情返回 404；limit 为 1–100。BIGINT ID 以字符串返回，时间以 UTC ISO 8601 返回。

先在 app 目录人工执行迁移 `.venv/bin/python -m alembic upgrade head`（Windows 使用 `.venv/Scripts/python.exe`），再启动服务。此次只验证了离线 SQL，没有连接数据库、建表或执行在线迁移。

审计提供追溯，不提供断点续跑或工具重放。进程强制退出时未最终提交的任务/步骤可能仍为 running，started_at 可用于判别遗留记录；下次会话请求超过 5 分钟后释放旧消息占用，不会重新执行 Shell。消息与任务使用独立短事务，数据库故障窗口可能导致二者最终状态暂时不一致，查询时以各记录及错误为准。


### 免密钥天气工具

`get_weather(city, search_name?, country_code?, forecast_date?)` 使用 [Open-Meteo Geocoding](https://open-meteo.com/en/docs/geocoding-api) 查坐标，再使用 [Forecast API](https://open-meteo.com/en/docs) 获取当前条件与未来 7 天预报。非商业公共 API 无需密钥；商业部署需按供应商方案替换配置。通过 AGENT_WEATHER_ENABLED 开关控制，默认 true，独立于 AGENT_WEB_ENABLED 和 TAVILY_API_KEY，但仍受 AGENT_ENABLED 总开关、超时、stop 和审计约束。

例如城市武汉可传 `{"city":"武汉","search_name":"Wuhan","country_code":"CN"}`；中文无结果时尝试英文名。同名地点返回候选要求确认省份/国家；不猜用户位置。未传 forecast_date 时以城市时区的今天为准，返回日期、数据有效时间、单位和来源 URL；不把模型预报描述成气象站实测。历史日期或超出未来 7 天范围会明确失败。固定 HTTPS 服务地址，无需修改数据库表或增加依赖。

服务重启后，天气优先用 get_weather，不会因 Tavily 密钥为空而拒绝天气查询。新闻、网页资料在默认 auto 模式下也可使用免密钥公开搜索，Tavily 密钥为可选。服务器本身也必须能访问 Open-Meteo，DNS/代理/连接错误会返回 weather_unavailable，不能用静态天气冒充联网结果。

## 持久化定时任务

安装更新后的 requirements.txt，并在 **app 目录手动执行**：

```powershell
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m uvicorn main:app --reload
```

新增迁移 `20261019_0004` 创建 `scheduled_tasks`、`scheduled_runs`，本次开发只生成离线 SQL，没有执行在线迁移。服务生命周期只装配资源和启动调度器，不建表、不迁移、不做数据库探活；调度器首次在 2 秒后的正常扫描中访问数据库。未迁移时任务接口返回 503，调度器记录安全错误并等待下轮。

直接在对话中说“北京时间每天早上 9 点查询武汉天气”，AI 提取任务名称、可独立执行的提示词、计划和时区，通过 create_scheduled_task function call 保存。缺少时区、准确时间或任务内容时先追问，用户补充后结合历史继续创建；信息完整的明确请求直接创建，无需手填表单或重复确认。支持一次性、每天、每周和自定义 Cron。左侧“定时任务”分页查询当前用户全部任务，保留编辑、停止/恢复、立即运行及跳转会话。会话中展开任务查看运行记录和结果预览，点击定位完整回答。前端每 5 秒刷新任务、展开记录的全部已加载页及当前会话消息，聊天结束时也刷新任务。消息刷新保留已加载的历史，不覆盖正在进行的 SSE，也不在用户向上阅读时强制滚到底部。

### 对话工具与 Skill

内置运行时 Skill 为 `app/skills/scheduled-tasks/SKILL.md`，由现有 FileSkillSource 发现，模型按需调用 load_skill 加载。Skill 指导提取自包含的执行 prompt：例如“北京时间每天九点查询武汉天气”保存为“查询武汉今天的天气，给出天气、温度和降水建议”，调度规则另存；周期任务不写死创建当天日期，也不把“创建任务”等措辞留在执行提示词中。只提供新 Skill 文件时重启即可发现；自定义 AGENT_SKILLS_DIR 的部署需将该 Skill 放入所配置目录。

`create_scheduled_task` 参数仅为 name、prompt、kind、timezone、cron、run_at。工具在每轮执行时绑定服务端的 user_id、conversation_id 和 user_message_id，不接受模型指定身份或会话。共享注册表不保存可变的当前用户，多个并发会话分别创建独立的上下文工具实例。工具复用现有校验与仓储，提交成功后才返回 `ok=true, persisted=true, task=...`；模型据此反馈任务及下次运行时间，纯文本“已创建”不代表保存。

同一用户消息内，以规范化计划和提示词计算稳定 request_id，相同调用即使换了 tool_call_id 或名称也返回已有任务；不同用户消息允许用户明确要求再次创建，不提供跨聊天请求的全局去重。模型/工具快照、Skill 内容与 hash、创建参数及实际返回均沿用 Agent 审计。关闭 AGENT_ENABLED 时不提供创建能力。

后台运行和立即运行都使用 scheduled_execution 上下文，工具列表中移除 create_scheduled_task，伪造调用也被拒绝，避免递归创建任务。未注册的编辑/停止工具不能由 AI 假装调用，当前仍在任务管理页面操作。创建结果已保存但聊天随后断开或停止时，任务保留，可从列表核实。

### 存储和执行

APScheduler 3.x 的 AsyncIOScheduler 每 2 秒唤醒持久化队列，CronTrigger 计算周期计划；业务任务、下次运行时间、暂停状态、手动运行请求、提示词快照与执行记录全部保存于 MySQL。未使用 SQLAlchemyJobStore（其启动会自动建表，且不能由多个调度器共享）；进程内仅保留可重建的扫描作业及正在执行的协程，重启不依赖这些内存数据恢复业务任务。参见 [APScheduler 官方指南](https://apscheduler.readthedocs.io/en/3.x/userguide.html)。

任务按用户和会话归属隔离，沿用 X-User-Id。扫描在短事务中用 FOR UPDATE SKIP LOCKED 锁定任务、检查运行状态并写入唯一运行记录；网络调用期间不持有事务。同一任务一次最多一个 running，多进程读取同一数据库也通过行锁认领；每进程最多 4 个执行协程。建议 Demo 使用单个 Uvicorn worker；多进程会分别扫描、总并发上限为 worker 数乘 4，不提供分布式公平排队。

每次执行复用现有 Agent、工具权限、上下文和超时预算（移除任务创建工具），将提示词和回答写入任务原会话，并保留 Agent 审计。消息 ID 与运行记录在同一事务中关联；运行详情中的 assistant_message_id 可直接定位消息。失败前尚未创建消息时也保存可定位的失败回答。会话正在生成时通常延后认领；极小的并发窗口若遇到会话忙会记录失败，用户可以手动重跑。

### 时间和恢复策略

- 一次性计划使用 `kind=once` 和带 UTC 偏移的 ISO 8601 `run_at`；周期计划使用 `kind=cron`、五段 `cron` 和明确的 IANA `timezone`。数据库 DATETIME 均为 UTC；API 返回带 +00:00 的时间；界面按任务时区展示。Windows 使用 tzdata 提供时区数据。
- Cron 顺序为“分 时 日 月 星期”；星期数字采用 APScheduler 语义：0 为周一，推荐 mon–sun。日和星期条件同时指定时需同时满足。每天 09:00 为 `0 9 * * *`，每周一 09:00 为 `0 9 * * mon`。
- 夏令时跳过不存在的周期墙钟时刻；回拨的重复时刻按不同 UTC 时刻区分，可能各执行一次。一次性 API 由 run_at 的偏移明确时刻；表单拒绝不存在或重复的当地时间，重复时可使用 UTC 时区指定。
- 重启后读取数据库中保存的待执行时间。过期一次性任务执行一次；周期任务错过多次时合并为一次，再按当前时刻计算下一次，不追赶全部历史。暂停期间不执行周期计划，恢复时从当前时刻计算；过期一次性任务须先编辑未来时间。
- 停止仅停止后续计划，已排队的手动请求和正在执行的任务继续完成。“立即运行”先持久化 queued，再返回 202；独立于暂停状态，不移动原有定时计划。一个任务已有 queued/running 时返回 409。创建和立即运行要求 request_id UUID，分别按用户、任务去重；响应丢失后以同一 request_id 重试。
- 模型与工具执行失败不自动重试。整体执行预算包含准备阶段，沿用 AGENT_TIMEOUT_SECONDS，默认 120 秒、最大 240 秒；超时取消模型/工具并保存 failed 和明确错误，取消清理及数据库 I/O 可能增加实际结束耗时。协程发生异常也会结束关联消息、Agent 审计及会话占用，避免消息永久处于 generating。正常关闭保存 cancelled。
- 结束状态写入遇到 storage_unavailable 最多尝试 3 次（间隔 0.25、0.5 秒），只重试幂等状态保存，不重复调用模型或工具。若回答已提交而运行记录仍为 running，下一轮扫描直接同步已保存的终态，不再等 10 分钟；没有终态回答的遗留 running 仍在认领满 10 分钟后转为 failed 并释放会话占用。恢复扫描不重放工具，不承诺恰好一次执行。日志以 run ID 关联开始、超时、异常和状态写入，便于排查。

任务状态为 active（启用）、paused（停止）、completed（一次性计划已触发、无下次计划）；completed 表示计划已派发，实际成功与否查看运行状态。运行状态为 queued、running、completed、failed、cancelled。

### API

全部接口要求已有用户的 X-User-Id，越权任务返回 404；limit 为 1–100，offset 为 0–100000。BIGINT 消息 ID 以字符串返回。

| 接口 | 用途 |
|---|---|
| GET /api/scheduled-tasks?conversation_id=UUID&offset=0&limit=30 | 分页列表，省略 conversation_id 查询当前用户全部任务 |
| POST /api/scheduled-tasks | 创建并确认持久化；返回 201 |
| POST /api/scheduled-tasks/{id}/edit | 替换名称、提示词和计划，保留原会话及已排队执行的快照 |
| POST /api/scheduled-tasks/{id}/state | 设置 status 为 active / paused |
| POST /api/scheduled-tasks/{id}/run | 持久化立即运行请求，返回 202 和运行记录 |
| GET /api/scheduled-tasks/{id}/runs?offset=0&limit=20 | 分页执行记录，含时间、状态、错误、提示词快照、assistant_message_id、message_status、result_preview（最多 2000 字符）和 result_truncated |

以下为保留的底层创建 API 请求示例，供开发调试；前端创建通过 AI function call 完成，工具自动绑定 conversation_id 和生成 request_id。编辑 API 使用相同计划字段，去掉 conversation_id 和 request_id：

```json
{
  "conversation_id": "替换为已有会话UUID",
  "request_id": "替换为本次请求UUID",
  "name": "每日学习建议",
  "prompt": "生成一条学习建议",
  "kind": "cron",
  "timezone": "Asia/Shanghai",
  "cron": "0 9 * * *",
  "run_at": null
}
```

一次性请求改为 `kind=once`、`cron=null` 和未来的 `run_at`。立即运行请求体为 `{"request_id":"本次请求UUID"}`；停止为 `{"status":"paused"}`。现有 /api/chat SSE 事件和会话接口保持兼容。

### 验证

`./.venv/Scripts/python.exe -m unittest discover -s tests -p test_schedules.py -v` 使用临时 SQLite 文件、兼容 DDL 和模型替身，覆盖对话 function call 创建、Skill 加载与审计、多轮补充信息、身份隔离、同轮创建去重、后台禁止递归创建，以及持久化重读、队列、结果与消息关联、暂停编辑、过期合并、夏令时、关闭取消和中断恢复。模型替身验证调用链，不代表真实模型的意图与提示词提取效果已联调；SQLite 不验证 MySQL 行锁竞争。线上迁移、真实 MySQL 并发及付费模型调用需在实际环境另行验证。

执行状态回归还覆盖 running→completed 的 API 查询、异常结束关联消息、准备阶段超时、终态写入临时失败后的重试，以及已保存结果的立即恢复。前端在 front/ 执行 `node --experimental-strip-types --test tests/background-updates.test.ts`，使用 Node 自带测试器检查后台消息更新、保留历史、延迟响应防回退和执行记录翻页后的刷新；该检查不替代浏览器联调。
