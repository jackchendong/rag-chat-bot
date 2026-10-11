import hashlib
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..domain.agent import SkillSource, Tool, ToolError


class FileSkillSource(SkillSource):
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def load(self, name: str) -> dict[str, str]:
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name):
            raise ToolError('invalid_skill', 'Skill 名称无效')
        path = (self.root / name / 'SKILL.md').resolve()
        if not path.is_relative_to(self.root) or not path.is_file() or path.stat().st_size > 32000:
            raise ToolError('invalid_skill', 'Skill 不存在或超过长度限制')
        try:
            content = path.read_text(encoding='utf-8')
            parts = content.split('---', 2)
            meta = yaml.safe_load(parts[1]) if len(parts) == 3 and parts[0].strip() == '' else None
            if not isinstance(meta, dict) or meta.get('name') != name or not isinstance(meta.get('description'), str):
                raise ValueError
            if not 1 <= len(meta['description']) <= 500:
                raise ValueError
        except (OSError, UnicodeError, ValueError, yaml.YAMLError):
            raise ToolError('invalid_skill', 'SKILL.md 必须包含有效的 name 和 description YAML frontmatter') from None
        return {'name': name, 'description': meta['description'], 'content': content,
                'sha256': hashlib.sha256(content.encode()).hexdigest()}

    def catalog(self) -> list[dict[str, str]]:
        if not self.root.is_dir():
            return []
        result = []
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and not directory.name.startswith('.'):
                skill = self.load(directory.name)
                result.append({key: skill[key] for key in ('name', 'description', 'sha256')})
                if len(result) > 32:
                    raise ToolError('invalid_skill', 'Skills 数量超过 32 个')
        return result


class LoadSkillArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=64)


class LoadSkillTool(Tool):
    def __init__(self, source: SkillSource) -> None:
        self.source = source

    @property
    def definition(self) -> dict[str, Any]:
        return {'type': 'function', 'function': {'name': 'load_skill',
            'description': '加载目录中指定 Skill 的完整操作指令；不执行代码，也不增加工具权限。',
            'parameters': LoadSkillArgs.model_json_schema()}}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = LoadSkillArgs.model_validate(arguments)
        # Small bounded local files. The returned content and hash are persisted as a tool step.
        return {'ok': True, **self.source.load(args.name)}
