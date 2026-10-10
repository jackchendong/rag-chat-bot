---
name: python-typing
description: 设计或修复 app Python 的类型边界、结构化数据、Protocol、TypedDict、泛型和静态检查问题。仅在任务涉及类型契约时使用，不自动引入校验框架或类型检查工具。
---

# Python 类型与边界

## 选择合适的数据表达

- 内部值对象优先使用已有类型，确需命名结构时考虑 dataclass；JSON 字典契约可用 TypedDict，运行时输入校验使用项目已选定的方法。
- TypedDict、NewType、类型别名和 `cast` 不自动执行运行时校验，也不能作为授权、数据清洗或格式转换。
- 参数只需要遍历时考虑 `Iterable`，需要索引时考虑 `Sequence`，只读键值接口考虑 `Mapping`；确需修改时才要求可变容器。
- 可变容器的类型不能随意放宽：`list[Derived]` 不是可任意替代 `list[Base]` 的写入容器。根据实际读写语义选择接口，不用 `cast` 绕过。
- 使用 Enum 或 Literal 表达有限状态时，以真实后端契约为准，不为了类型设计新增业务状态。

## 函数与依赖契约

- 返回值明确区分成功、没有数据与失败。`None` 是否合法应在类型与处理逻辑中一致，不让所有失败都退化为 `None`。
- 模型、存储或时钟确需可替换时，定义消费方所需的最小 Protocol，不复制 SDK 的庞大接口，也不为每个函数创造接口。
- Protocol 的静态结构检查不保证运行时业务契约；即使使用 `runtime_checkable`，也不能认为方法签名和返回数据已经被完整校验。
- 异步函数标注 await 后得到的值；普通函数返回协程或 awaitable 时明确区别。装饰器需要保留参数类型时按需使用 ParamSpec，不到处套用复杂泛型。
- 使用类型收窄后再访问可选值；引入 TypeGuard 时保证判断真的成立，不以注解代替验证。
- 类型注解相关导入可能在运行时被框架读取。使用 TYPE_CHECKING 或延迟注解前，检查反射、序列化和框架的真实需求。

## Python 3.10 兼容性

- 使用已有版本支持的语法；`Self`、`Required`、`NotRequired` 等更高版本标准库名称不能直接从 Python 3.10 的 typing 导入。
- 只有确需这些能力且项目已有或明确允许引入 `typing_extensions` 时使用回移版本，不为简单数据结构增加依赖。
- 静态检查工具按项目配置运行；错误优先修复真实类型和数据边界，必要的 ignore 应限定错误类别并有清晰理由，不全文件禁用检查。

具体名称与版本查阅 [Python 3.10 typing 文档](https://docs.python.org/3.10/library/typing.html)。
