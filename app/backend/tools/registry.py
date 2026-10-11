import json
import logging
from typing import Any

from pydantic import ValidationError

from ..domain.agent import Tool, ToolError, ToolExecutor

logger = logging.getLogger(__name__)


class ToolRegistry(ToolExecutor):
    def __init__(self, tools: list[Tool]) -> None:
        self.tools = {tool.definition['function']['name']: tool for tool in tools}
        if len(self.tools) != len(tools):
            raise ValueError('Duplicate tool registration')

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.definition for tool in self.tools.values()]

    async def execute(self, name: str, arguments: str) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            raise ToolError('unknown_tool', '工具未注册或已被管理员禁用')
        try:
            if len(arguments) > 16000:
                raise ValueError
            values = json.loads(arguments)
            if not isinstance(values, dict):
                raise ValueError
            return await tool.execute(values)
        except (ValidationError, ValueError):
            raise ToolError('invalid_arguments', '工具参数必须是符合定义的 JSON 对象') from None
        except OSError:
            raise ToolError('tool_unavailable', '工具暂时无法执行') from None
        except ToolError:
            raise
        except Exception as error:
            # Tool extensions are an execution boundary. Do not expose raw exceptions or secrets.
            logger.error('Tool failed name=%s exception=%s', name, type(error).__name__)
            raise ToolError('tool_failed', '工具执行失败') from None
