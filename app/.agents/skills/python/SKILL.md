---
name: python
description: 实现、修改、审查或调试 rag-chat-bot 的 app Python 后端，按任务选择语法、类型、设计、异步、调度、测试和工具链技能。不用于前端开发，也不代表后端框架已经选定。
---

# Python 后端工作入口

先阅读 `app/AGENTS.md`、相关实现、依赖清单和测试（如存在），确认真实运行环境及前后端契约。项目当前以 Python 3.10 为兼容基线，不能根据全局 Python 版本推断应用版本。

## 按需读取

| 任务 | 技能 |
|---|---|
| 编写或审查函数、类型、容器、异常、资源管理及语言语法 | [Python 语法](../python-syntax/SKILL.md) |
| 类型边界、Protocol、TypedDict、泛型及静态检查问题 | [Python 类型](../python-typing/SKILL.md) |
| 模块划分、配置、依赖注入、错误建模与 API 边界 | [Python 设计](../python-design/SKILL.md) |
| async/await、并发、超时、取消、流式响应及后台生命周期 | [Python 异步](../python-async/SKILL.md) |
| 定时任务、持久化认领、时区、重启恢复与重复执行 | [Python 调度](../python-scheduling/SKILL.md) |
| 回归测试、mock、时间相关测试及外部接口验证 | [Python 测试](../python-testing/SKILL.md) |
| 虚拟环境、依赖维护、语法检查、格式化及类型检查 | [Python 工具链](../python-tooling/SKILL.md) |
| 修改运行行为前明确需求、兼容边界和实现范围 | [实现策略](../implementation-strategy/SKILL.md) |
| 收尾检查任务完整改动和高风险边界 | [实现收尾审查](../implementation-final-review/SKILL.md) |
| 代码、测试、依赖或检查配置改动后的最终验证 | [改动验证](../code-change-verification/SKILL.md) |
| 审查或同步 README、配置与启动说明 | [文档同步](../docs-sync/SKILL.md) |
| 用最小可控实验验证真实运行行为 | [运行行为探测](../runtime-behavior-probe/SKILL.md) |
| 审查或修复日志、异常和诊断中的敏感数据泄露 | [敏感日志审查](../sensitive-logging-audit/SKILL.md) |

## 工作方式

- 先确定调用路径、输入输出、错误和资源所有者，再做最小内聚改动。
- 使用实际安装的库和版本，不凭参考项目推断依赖存在。
- 业务实现以 `app/AGENTS.md` 为准；通用语言细节由相关技能维护。
- 有测试体系时验证可观察行为，不能通过吞异常、删断言或替换真实结果来掩盖失败。
- 报告真实运行的检查和限制；本技能不要求新建分支、提交代码、发布服务或修改机器配置。

## 任务范围

小型函数修复通常只需语法技能；类型错误再加载类型技能，不为简单改动强制重构架构。涉及后台任务时同时检查异步资源生命周期与调度一致性，两者不能互相替代。纯技能文档维护不启动服务，不调用真实模型，也不建立尚未选定的应用依赖。

工程流程按实际改动选择：运行行为变更先明确范围，再做聚焦验证、收尾审查和适用的最终检查；文档或技能元数据改动只运行相关检查。探测、敏感日志专项审查和覆盖率测量不是所有任务的必经步骤。

## 参考与适配边界

工程流程参考 [OpenAI Agents Python 官方技能](https://github.com/openai/openai-agents-python/tree/f9da374e17a6ee09c5831e8a0075e7b6e9f1081b/.agents/skills)，检索日期为 2026-10-10。本项目保留独立的语言技能，工作流按 Python 3.10、Windows/Git Bash 和当前 Demo 状态改写，不是官方技能的原样安装。

不继承参考仓库的 `make`、uv、SDK 目录、翻译发布规则、强制 worktree/commit 或固定多轮独立审查。独立审查只在用户要求或风险确有需要且能力可用时开展；不可用时如实报告，不捏造审查通过。
