import asyncio
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any

import anyio
from pydantic import BaseModel, ConfigDict, Field

from ..domain.agent import Tool, ToolError

# Each command has a validated argument grammar, not just a binary-name allowlist.
SUPPORTED_COMMANDS = frozenset({'pwd', 'ls', 'date', 'echo', 'uname', 'whoami'})


class ShellArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    argv: list[str] = Field(min_length=1, max_length=32)


class ShellTool(Tool):
    def __init__(self, workspace: Path, allowlist: str, output_limit: int = 12000) -> None:
        self.workspace = workspace.resolve()
        self.allowed = frozenset(part.strip() for part in allowlist.split(',') if part.strip())
        if not self.allowed or not self.allowed <= SUPPORTED_COMMANDS:
            raise RuntimeError('AGENT_SHELL_ALLOWLIST 仅支持 pwd,ls,date,echo,uname,whoami')
        self.output_limit = output_limit

    @property
    def definition(self) -> dict[str, Any]:
        return {'type': 'function', 'function': {'name': 'shell_exec',
            'description': f'在固定工作目录执行受限命令；允许 {",".join(sorted(self.allowed))}。只传 argv 数组，不支持 shell 语法。',
            'parameters': ShellArgs.model_json_schema()}}

    def validate(self, argv: list[str]) -> list[str]:
        if any(not value or len(value) > 1000 or any(c in value for c in '\x00\r\n') for value in argv):
            raise ToolError('invalid_arguments', '命令参数为空、过长或含控制字符')
        command, *args = argv
        if command not in self.allowed:
            raise ToolError('command_denied', '程序不在 Shell 白名单中')
        valid = False
        if command in ('pwd', 'whoami'):
            valid = not args
        elif command == 'ls':
            # Only list the workspace itself; no paths, symlinks, recursion or flags with arguments.
            valid = all(value == '.' or value in ('-a', '-l', '-h', '-al', '-la', '-lh', '-alh') for value in args)
        elif command == 'date':
            valid = not args or args == ['-u'] or len(args) == 1 and args[0].startswith('+')
        elif command == 'uname':
            valid = all(value in ('-a', '-s', '-r', '-m', '-n', '-v') for value in args)
        elif command == 'echo':
            valid = True  # Arguments are literal text, never evaluated by a shell.
        if not valid:
            raise ToolError('arguments_denied', '命令参数不在允许的格式中')
        binary = shutil.which(command, path=os.defpath)
        if not binary:
            raise ToolError('command_missing', '服务器未安装该程序')
        return [binary, *args]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = ShellArgs.model_validate(arguments)
        argv = self.validate(args.argv)
        self.workspace.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {'start_new_session': True} if os.name == 'posix' else {
            'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
        process = await asyncio.create_subprocess_exec(*argv, cwd=self.workspace,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'HOME': str(self.workspace)},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
        total = 0

        async def collect(stream: asyncio.StreamReader) -> bytes:
            nonlocal total
            result = bytearray()
            while part := await stream.read(4096):
                total += len(part)
                if total > self.output_limit:
                    raise ToolError('shell_output_limit', 'Shell 输出超过限制，进程已终止')
                result.extend(part)
            return bytes(result)

        readers = [asyncio.create_task(collect(process.stdout)), asyncio.create_task(collect(process.stderr))]
        try:
            stdout, stderr = await asyncio.gather(*readers)
            exit_code = await process.wait()
            return {'ok': exit_code == 0, 'exit_code': exit_code,
                    'stdout': stdout.decode('utf-8', errors='replace'), 'stderr': stderr.decode('utf-8', errors='replace')}
        except OSError:
            raise ToolError('shell_unavailable', 'Shell 进程执行失败') from None
        finally:
            # Stop the entire group and reap children even on SSE disconnect/stop/timeout/output overflow.
            with anyio.CancelScope(shield=True):
                if os.name == 'posix':
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.returncode is None:
                    process.kill()
                for reader in readers:
                    if not reader.done():
                        reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                await process.wait()
