# 仓库工作规范

本文件适用于仓库根目录及所有子目录。修改文件前读取目标目录及其父目录的 `AGENTS.md`；更深层规范优先，用户明确要求优先于项目约定。

## 项目与当前能力

本项目是前后端分离的大模型对话 Demo，目标是普通对话及通过对话创建后台定时任务。

- `front/`：Vue 3、TypeScript、Vite、Tailwind CSS，使用 pnpm；当前是 Hello World 占位页面，尚未接入后端。
- `app/`：Python 3.10、FastAPI、HTTPX，已实现 DeepSeek 单轮 SSE 对话接口。
- 数据库采用 MySQL、SQLAlchemy 2.0、PyMySQL 和 Alembic，已有用户表 ORM 与初始迁移；是否已应用迁移以实际数据库状态为准，不根据迁移文件推断。
- 会话历史、用户 CRUD、认证、RAG、任务持久化与定时调度尚未实现。不把产品目标、文档示例或目录规划表述为已实现能力。

## 工作入口与职责

- 开始任务先检查 `git status --short`、相关实现与实际依赖，保留用户已有改动，不覆盖或回退无关文件。
- 前端工作读取 `front/AGENTS.md`，按任务加载 `front/.agents/skills/` 的相关技能。
- 后端工作读取 `app/AGENTS.md`；涉及 Python 实现或审查时先读取 `app/.agents/skills/python/SKILL.md`，再按需加载相关技能。
- 仓库总体说明见 `README.md`；后端运行、配置、分层和手动迁移说明见 `app/README.md`。存在文档与代码差异时先核实实际行为。
- 只修改任务所需模块。后端任务不顺带调整前端；跨模块契约变更明确影响范围并同步相关文档。
- 根目录保留仓库级规范和工具入口，不放置前端业务或后端实现，不为结构完整创建空目录或抽象层。

## 依赖与运行环境

- 前端使用 `front/package.json` 和 `front/pnpm-lock.yaml`，不混用 npm、yarn 锁文件。当前声明 Node.js >=24、pnpm 11.3.0，以实际清单为准。
- 后端使用 `app/.venv` 的解释器和 pip；依赖版本只维护在 `app/requirements.txt`。
- 不在根目录重复维护后端依赖版本；若需增加根目录 requirements 入口，仅引用 `app/requirements.txt`，不新增平行依赖管理方案。
- Windows 后端解释器为 `app/.venv/Scripts/python.exe`。PowerShell 调用时可使用 `&`，Git Bash 使用 `./` 路径；不要默认使用全局 `python` 或 `pip`。
- 保持现有 Git Bash 和 VS Code 配置约定，不修改 `.bashrc`、系统解释器或全局工具配置。

## 接口与业务边界

- 保持 `POST /api/chat` 和现有 `message`、`done`、`error` SSE 事件契约；内部重构不顺带修改路径、字段或成功语义。
- 模型请求和私密凭据只在后端处理。前端 `VITE_*` 变量会暴露给浏览器，不能放入密钥或数据库密码。
- 用户输入、模型输出与任务结果是不可信内容，不能直接作为 shell、Python、SQL 字符串或不安全 HTML 执行。
- 后台调度属于后端职责，不能依赖页面定时器或进程内临时列表冒充持久化。真实保存成功后才能报告任务已创建。
- 后端保持现有轻量分层：入口只创建应用，API 处理传输，服务依赖领域契约，外部适配与资源由应用生命周期装配。

## 数据库与安全限制

- 密钥和数据库连接信息只写入本地 `.env` 或环境变量；可提交的 `.env.example` 只包含占位值。不在文档、日志、异常或最终回复中重复真实凭据。
- 不读取或输出完整 `.env` 来排查普通配置问题；优先验证变量名称、是否存在和脱敏结果。
- 服务启动不得自动建表、执行迁移或进行数据库探活。表结构变更同步维护 ORM 和独立 migration，历史 migration 不依赖当前 ORM。
- 用户要求手动迁移时，只编写迁移并做离线验证；未经明确授权，不连接远程数据库，不执行在线 upgrade、downgrade、autogenerate、current 或探活。
- 离线 SQL 生成不代表迁移已经应用。回退、删表和数据修改具有副作用，不擅自执行；数据库事务和 UTC 时间约定遵循后端规范。
- 不默认调用真实付费模型进行验证，优先使用替身和 HTTPX MockTransport。
- 不提交 `.env`、`.venv/`、`node_modules/`、构建产物、缓存、日志或运行数据；不绕过 `.gitignore` 加入秘密。

## 验证与交付

在对应模块目录执行命令，先做聚焦检查，再运行与改动相关的现有检查：

| 工作目录 | 命令 | 用途 |
|---|---|---|
| `front/` | `pnpm typecheck` | 前端类型检查 |
| `front/` | `pnpm build` | 类型检查与构建 |
| `app/` | `./.venv/Scripts/python.exe -m compileall -q main.py backend migrations` | Python 语法检查 |
| `app/` | `./.venv/Scripts/python.exe -m pip check` | 已安装依赖一致性 |
| `app/` | `./.venv/Scripts/python.exe .agents/skills/code-change-verification/scripts/validate_skills.py` | 本地技能结构与引用检查 |
| 仓库根目录 | `git diff --check` | 补丁空白检查 |

- 纯文档改动只检查格式、引用和内容一致性，不安装应用依赖、不启动服务、不连接数据库或模型。
- 当前没有正式测试体系或统一 lint 配置；不要为小任务引入整套工具，也不要把语法检查称为业务测试。
- 不修复无关问题，不关闭检查、吞掉异常或删除断言来伪装验证成功。
- 修改接口、配置、依赖或启动流程时同步相应 README；避免在多份规范中重复整套语言教程。
- 除非用户明确要求，不创建分支、不提交代码、不部署、不发布，也不执行破坏性清理。
- 交付使用简洁中文，说明改动、实际验证及未执行事项。无法验证 IDE 提示或真实联调时如实说明，不声称已经确认。
