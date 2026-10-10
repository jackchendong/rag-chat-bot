---
name: fastapi-architecture
description: 维护 app FastAPI 后端的路由、Schema、服务、领域契约、模型适配及应用生命周期分层。用于添加接口或重构模块，不强制引入数据库、Repository、认证或完整 DDD 框架。
---

# FastAPI 轻量分层

先阅读 `app/AGENTS.md` 和 `app/README.md`，确认实际入口与接口契约。目录分工参考 [fastapi-clean-architecture](https://github.com/keanallen/fastapi-clean-architecture/tree/960f0a861e1024ae5495c3f812e95db238231484/app)，但以当前实现为准，不复制其数据库、鉴权或全局服务实例。

## 文件落点

| 职责 | 当前位置 |
|---|---|
| Uvicorn 入口 | `app/main.py`，仅调用应用工厂 |
| 应用创建、资源生命周期及装配 | `app/backend/application.py` |
| HTTP 路由和依赖注入 | `app/backend/api/routes/`、`api/deps.py` |
| SSE 编码、响应头和断连清理 | `app/backend/api/responses.py` |
| 外部请求字段校验 | `app/backend/schemas/` |
| 回答业务编排 | `app/backend/services/` |
| 模型网关、数据事件与安全错误 | `app/backend/domain/` |
| 模型 HTTP 与供应商流解析 | `app/backend/providers/` |
| .env 与配置校验 | `app/backend/core/config.py` |

## 依赖与生命周期

- API 调用服务，服务依赖领域协议，供应商适配实现协议；领域不能反向导入 API、配置、HTTPX 或 FastAPI。
- `application.py` 是装配边界，可同时引用外部适配和服务，禁止从领域或服务反向导入应用。
- 路由只处理 HTTP 与服务调用，不内联供应商请求；服务返回 ChatEvent 等普通数据，不返回 Response、HTTP 状态或 SSE 字符串。
- 供应商解析模型私有字段，服务与 API 使用稳定的 ModelChunk；数据库模型与 HTTP Schema 也是不同职责，未来有持久化时再创建。
- 使用应用级 lifespan 创建和关闭共享客户端，Depends 获取已装配服务，不在导入时创建网络客户端或读取密钥。
- 通过服务注入和 ModelGateway 替换真实模型，测试不要求默认使用付费 API。服务不关闭应用拥有的客户端，但必须关闭自己迭代的流。
- 保持标准包导入及现有 `main:app` 启动方式；从根目录启动用 `--app-dir app`，不用修改 sys.path，也不同时用不同模块名加载同一应用。

## SSE 改动检查

- 保持 `POST /api/chat`、请求字段和 `message/done/error` 格式；分层不意味着增加 `/v1` 或变更事件名称。
- 输入错误发生在流建立前；上游失败在流中报告，HTTP 200 不等于回答成功，不在流启动后试图改状态码。
- 分块解析保留 UTF-8、换行、多行 data、正常结束和意外断流语义。
- 关闭链包含响应编码器、服务流、供应商流和上游 response；finally 清理需要在取消下完成，CancelledError 不转换为业务错误。
- 供应商异常转为安全领域错误，再由服务输出 error；不将原始异常或凭据序列化给客户端。

## 扩展与验证

添加接口先确定路由、输入 Schema 与服务职责。新增供应商只调整适配和装配，不复制聊天业务。持久化与调度只有确需时才增加，不为结构完整提前建立空层。

完成重构后验证旧入口启动、.env 定位、HTTP 校验、OpenAPI、SSE 帧、上游失败、取消清理和生命周期关闭，更新后端及根 README。纯架构文档改动只验证元数据、引用和规则适用性，不启动真实模型任务。
