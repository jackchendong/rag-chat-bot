# 大模型对话 Demo

一个采用前后端分离架构的大模型对话演示项目，分为前端和后端两个模块，目标是支持普通对话，以及通过对话创建并在后台运行定时任务。

> 前端暂为 Hello World，尚未接入后端。后端已实现 DeepSeek 单轮对话 SSE 接口；会话历史、定时任务与 RAG 尚未实现。

后端已加入 MySQL 连接配置、四字段用户表 ORM 与 Alembic 初始迁移，尚未执行迁移；手动升级步骤见 `app/README.md` 的“MySQL 与手动迁移”。服务启动不会自动建表或迁移，当前没有用户 CRUD 或认证接口。

## 功能目标

- **普通对话**：用户发送消息，由大模型生成回复，支持日常问答等简单交互。
- **对话创建任务**：用户通过自然语言表达任务内容和执行时间，系统识别意图并确认任务信息。
- **后台定时执行**：任务创建后，由后台在指定时间执行，不要求用户持续停留在聊天页面。
- **执行结果反馈**：记录任务执行状态和结果，方便用户查看。

## 使用场景

以下为预期完整产品的交互示例；目前普通对话可通过后端接口调用，前端聊天与定时任务尚未实现。

### 普通对话

```text
用户：帮我解释一下什么是大语言模型。
助手：大语言模型是一类通过大量文本训练、能够理解和生成自然语言的模型……
```

### 创建定时任务

```text
用户：每天上午 9 点生成一条学习建议。
助手：请确认：每天上午 9 点生成学习建议。你希望使用哪个时区？
用户：北京时间。
助手：已创建任务，每天上午 9 点（Asia/Shanghai）在后台执行。
```

任务执行后的结果展示方式将在实现阶段确定；目前不承诺邮件、短信或其他外部通知能力。

## 模块划分

### 前端模块（`front/`）

负责用户交互和信息展示，预期包括：

- 聊天页面、消息输入和对话内容展示。
- 定时任务信息的确认交互。
- 任务执行状态和结果展示。
- 通过后端接口提交消息并获取回复、任务信息。

### 后端模块（`app/`）

负责对话处理和后台任务运行，预期包括：

- 提供前端所需的对话和任务接口。
- 调用大模型，处理普通对话与任务创建意图。
- 保存任务内容、执行时间、时区及执行状态。
- 调度和执行后台定时任务，记录执行结果。
- 管理大模型凭据及服务端配置。

前端负责展示和交互，后端负责模型调用与任务调度；关闭前端页面不应中断已创建的后台任务，但任务运行需要后端服务持续可用。

## 项目结构

```text
rag-chat-bot/
├── app/         # FastAPI 后端，含 DeepSeek SSE 对话接口
├── front/       # 前端模块（已初始化，Hello World 占位页面）
├── .gitignore
└── README.md
```

虽然仓库名为 `rag-chat-bot`，当前项目范围以普通对话和定时任务为主，尚未实现知识库检索或 RAG 能力。

## 预期工作流程

```text
用户在前端发送消息
    ↓
前端请求后端接口
    ↓
后端识别普通对话或定时任务意图
    ├── 普通对话 → 调用大模型 → 返回回复 → 前端展示
    └── 定时任务 → 确认任务内容、执行时间与时区
                    ↓
                 保存任务
                    ↓
                 后台调度执行
                    ↓
                 记录状态与结果
```

对于时间不明确、内容不完整的任务，应先向用户确认，再创建任务。

## 本地运行

### 前端

运行环境：Node.js 24 或更高版本、pnpm 11.3.0。前端采用 Vue 3、TypeScript、Vite 和 Tailwind CSS，并预留 shadcn-vue 组件配置。

在仓库根目录执行：

```powershell
cd front
pnpm install
pnpm dev
```

默认访问地址为 `http://localhost:5173`，端口被占用时以终端显示的地址为准。当前页面仅显示 Hello World，无需配置后端或大模型密钥。

其他命令（在 `front/` 中执行）：

```powershell
pnpm typecheck
pnpm build
pnpm preview
```

`pnpm build` 包含类型检查，构建产物位于 `front/dist/`。`pnpm preview` 用于本地预览构建产物，不是生产服务器。

### 后端

后端目录、分层职责、配置及扩展规范详见 [app/README.md](app/README.md)。启动入口和现有 SSE 协议保持不变。

使用 Python 3.10 或兼容版本，在 Git Bash 中从仓库根目录执行：

```bash
cd app
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m uvicorn main:app --reload
```

若尚无虚拟环境，先使用 Python 3.10 执行 `python -m venv .venv`。PowerShell 中可以用 `& ./.venv/Scripts/python.exe` 调用同一解释器。

根目录 `requirements.txt` 仅引用 `app/requirements.txt`，方便从仓库根目录打开项目时识别 Python 依赖；后端依赖版本仍统一维护在 `app/requirements.txt`。PyCharm 若提示包未列入 requirements，请确认项目解释器为 `app/.venv/Scripts/python.exe`，并在 Python → Tools → Integrated Tools 中将 Package requirements file for SDK 指向 `app/requirements.txt`（参见 [官方配置说明](https://www.jetbrains.com/help/pycharm/managing-dependencies.html#configure-requirements)）。不要通过关闭检查来隐藏提示。

配置位于 `app/.env`，新环境可以复制 `.env.example` 为 `.env` 后填写自己的密钥。配置项：

| 变量 | 用途 |
|---|---|
| `DEEPSEEK_API_KEY` | 必填，模型服务密钥，缺失时启动失败 |
| `DEEPSEEK_BASE_URL` | HTTPS 服务地址，默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash`，可替换为账户支持的模型 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 单次网络读写/连接池等待超时，默认 60 秒；连接超时为 10 秒，不是完整回答总耗时上限 |
| `MYSQL_HOST` / `MYSQL_PORT` | 数据库主机与端口，端口默认 3306 |
| `MYSQL_USERNAME` / `MYSQL_PASSWORD` | 数据库账号与密码，仅放本地 `.env` 或环境变量 |
| `MYSQL_DATABASE` | 已有数据库名称，迁移不创建数据库本身 |

系统环境变量优先于 `.env`。服务默认监听 `127.0.0.1:8000`，接口文档为 `http://127.0.0.1:8000/docs`。当前没有认证或限流，不应直接暴露到公网。

### SSE 对话接口

`POST /api/chat` 接收 `application/json`，字段 `message` 是去除首尾空白后的非空字符串，最多 10000 个字符，不接受其他字段。当前为单轮对话，不保存上下文。

在 Git Bash 执行下面的请求会调用真实模型并产生相应费用：

```bash
curl -N http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"你好，请简单介绍一下自己"}'
```

成功响应为 `text/event-stream`，按 SSE 空行分隔事件；`message.content` 是增量文本，需要客户端自行拼接，不是完整回答：

```text
event: message
data: {"content": "你好"}

event: message
data: {"content": "！"}

event: done
data: {"finish_reason": "stop", "truncated": false}

```

模型输出最多 1024 个 token，使用非思考模式；达到上限时 `done.truncated` 为 `true`。正常完成发送一次 `done`；上游错误、超时、无效数据或意外断流发送 `error` 并结束，不再发送成功事件：

```text
event: error
data: {"code": "upstream_timeout", "message": "模型服务响应超时，请稍后重试"}

```

输入不合法返回 HTTP 422；上游问题在已经建立的 SSE 响应中以 `error` 事件报告，因此 HTTP 200 本身不代表回答成功。客户端断开时释放流连接，但不保证供应商侧已经停止生成或计费。接口不自动重试，不返回供应商原始错误内容或密钥。

这是 POST SSE，浏览器原生 `EventSource` 不能直接传入该 JSON 请求，应使用 `fetch` 流读取或支持 POST 的 SSE 客户端。反向代理应禁用响应缓冲并设置足够的流式读取超时；当前前端未修改。

实现依据 [DeepSeek Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/) 的流式协议，任务存储、调度与默认时区的配置将在对应功能实现时补充。

大模型 API 密钥应由后端读取，不能写入前端代码或提交到版本库。

## 待实现事项

- [x] 单轮普通对话后端接口（DeepSeek + SSE）。
- [ ] 前端聊天页面及会话历史。
- [ ] 对话中的任务意图识别与信息确认。
- [ ] 定时任务持久化及后台调度。
- [ ] 任务执行状态与结果查询。
- [ ] 执行失败处理及服务重启后的任务恢复策略。
- [ ] 依赖说明、配置示例、启动步骤和测试。

## 项目边界

本项目定位为演示用途。生产使用前，还需完善身份认证、任务权限、资源限制、凭据保护及运行监控等能力。
