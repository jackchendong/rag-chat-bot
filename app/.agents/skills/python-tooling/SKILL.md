---
name: python-tooling
description: 维护 app 的 Python 虚拟环境、依赖和现有检查工具，执行语法、测试、格式化或类型验证。适用于环境诊断和交付检查，不自动安装整套工具链或升级解释器。
---

# Python 环境与工具链

## 解释器

以下命令在 `app/` 目录执行。Git Bash 使用：

```bash
./.venv/Scripts/python.exe --version
./.venv/Scripts/python.exe -m pip --version
```

PowerShell 使用 `& ./.venv/Scripts/python.exe` 调用同一解释器。不要把未激活终端中的 `python`、`pip` 当作虚拟环境命令，也不为切换解释器修改 `.bashrc`。

## 依赖

- 先检查 `pyproject.toml`、requirements 文件和锁文件是否存在，沿用实际方案；当前项目尚未选定。
- 使用选定工具生成对应锁文件，不手工编造依赖解析结果；不并行新增 pip、Poetry、uv 等多套管理方式。
- 项目采用 pip 时，通过目标解释器的 `-m pip` 执行，不使用全局 pip。安装依赖与更新清单须一致。
- 缺工具时报告限制。不要为纯文档检查修改应用环境或安装格式化、测试工具。
- 不以一次本地安装成功证明环境可复现；依赖变更核对 Python 版本约束和平台支持，并在清单、锁文件和运行说明中保持一致。
- 已采用 pip 时可用目标解释器执行 `-m pip check` 验证安装依赖关系，但它不替代导入验证、测试或锁文件检查。

## 验证

语法检查可使用标准库，仅对明确修改的文件执行，例如已有的 `main.py`：

```bash
./.venv/Scripts/python.exe -m py_compile main.py
```

这只验证语法，不证明导入、类型、接口或业务运行正确，也不要递归扫描 `.venv/`。

以下命令仅在工具已安装、项目已有相应配置及测试时使用：

```bash
./.venv/Scripts/python.exe -m pytest
./.venv/Scripts/python.exe -m ruff check .
./.venv/Scripts/python.exe -m ruff format --check .
./.venv/Scripts/python.exe -m mypy .
```

按已有配置选择工具，并限定到相关模块；这些示例不是要求同时安装或执行全部工具。格式化仅作用于目标代码，不机械重写整个项目。

启动服务使用项目真实存在的入口和依赖，不把 PyCharm 示例执行成功等同于后端接口可用。纯文档改动检查格式、技能元数据和引用即可。

## 诊断选择

- 先复现问题并记录解释器、依赖版本和入口，再针对症状诊断；不要用升级所有依赖作为默认修复。
- CPU 热点可用标准库 `cProfile`，分配问题可用 `tracemalloc`，挂起问题按需用 `faulthandler` 获取调用栈；仅在问题需要时启用，输出不得泄露凭据和敏感数据。
- 优化前用代表性输入测量，不用单次微基准替代端到端成本。区分 CPU 时间、网络等待、队列等待与模型延迟。
- 大范围 lint 或类型检查应遵循既有排除配置，不扫描 `.venv` 或生成文件。修复限定本次相关问题，不无条件加 `ignore` 或删除检查。

## 报告

列出实际运行的命令与结果，区分缺依赖、缺配置、外部服务不可用、既有问题和本次改动问题。不能把跳过检查或仅语法通过写成测试全部通过。
