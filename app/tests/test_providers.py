import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from pydantic import SecretStr, ValidationError

from backend.core.config import AgentSettings, Settings
from backend.domain.chat import ModelMessage
from backend.domain.errors import ModelServiceError
from backend.domain.agent import ToolError
from backend.providers.deepseek import DeepSeekClient
from backend.tools.web import TavilyTool, public_url
from backend.tools.shell import ShellTool


def frame(delta=None, finish=None):
    return 'data: ' + json.dumps({'choices': [{'delta': delta or {}, 'finish_reason': finish}]}) + '\n\n'


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def complete(self, body):
        def handler(request):
            self.sent = json.loads(request.content)
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'}, text=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            gateway = DeepSeekClient(client, Settings(api_key=SecretStr('mock')))
            return [chunk async for chunk in gateway.stream_answer([ModelMessage('user', 'hi')], [{'type': 'function'}])]

    async def test_fragmented_multiple_tool_calls(self):
        body = frame({'tool_calls': [
            {'index': 0, 'id': 'one', 'type': 'function', 'function': {'name': 'web_search', 'arguments': '{"query":'}},
            {'index': 1, 'id': 'two', 'type': 'function', 'function': {'name': 'shell_exec', 'arguments': '{"argv":'}}]})
        body += frame({'tool_calls': [
            {'index': 1, 'function': {'arguments': '["pwd"]}'}},
            {'index': 0, 'function': {'arguments': '"上海天气"}'}}]})
        chunks = await self.complete(body + frame(finish='tool_calls') + 'data: [DONE]\n\n')
        self.assertEqual(chunks[-1].tool_calls[0].id, 'one')
        self.assertEqual(json.loads(chunks[-1].tool_calls[1].arguments), {'argv': ['pwd']})
        self.assertEqual(self.sent['tool_choice'], 'auto')

    async def test_incomplete_and_duplicate_calls_rejected(self):
        calls = [{'index': i, 'id': 'same', 'function': {'name': 'shell_exec', 'arguments': '{}'}} for i in range(2)]
        for body in (frame({'tool_calls': [{'index': 0, 'function': {'arguments': '{}'}}]}, 'tool_calls') + 'data: [DONE]\n\n',
                     frame({'content': 'partial'}, 'stop'), frame(finish='tool_calls') + 'data: [DONE]\n\n',
                     frame({'tool_calls': calls}, 'tool_calls') + 'data: [DONE]\n\n'):
            with self.subTest(body=body), self.assertRaises(ModelServiceError): await self.complete(body)

    async def test_web_missing_key_and_private_url(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: self.fail('Unexpected request'))) as client:
            with self.assertRaises(ToolError) as error: await TavilyTool(client, '').execute({'query': 'weather'})
            self.assertEqual(error.exception.code, 'tool_not_configured')
            for url in ('http://127.0.0.1', 'http://10.0.0.2', 'http://localhost', 'https://a:b@example.com', 'file:///etc/passwd'):
                self.assertFalse(public_url(url))
                with self.assertRaises(ToolError): await TavilyTool(client, 'mock', read=True).execute({'url': url})

    async def test_web_result_has_provenance(self):
        def handler(request):
            self.assertEqual(request.url.host, 'api.tavily.com')
            self.assertNotIn('mock', request.content.decode())
            return httpx.Response(200, json={'results': [{'url': 'https://example.com/source', 'title': 'Source',
                'content': 'A' * 2000, 'published_date': '2026-10-11'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await TavilyTool(client, 'mock').execute({'query': 'weather'})
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['sources'][0]['content']), 1500)
        self.assertIn('fetched_at', result)

    async def test_cancelling_web_closes_response(self):
        closed, started = asyncio.Event(), asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b'{}'
            async def aclose(self): closed.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Body()))) as client:
            pending = asyncio.create_task(TavilyTool(client, 'mock').execute({'query': 'hi'}))
            await asyncio.wait_for(started.wait(), 1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertTrue(closed.is_set())

    async def test_shell_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolError) as error:
                await ShellTool(Path(tmp), 'echo', output_limit=20).execute({'argv': ['echo', 'x' * 100]})
            self.assertEqual(error.exception.code, 'shell_output_limit')

    async def test_shell_cancellation_reaps_process(self):
        if os.name != 'posix': self.skipTest('POSIX process group assertion')
        with tempfile.TemporaryDirectory() as tmp:
            tool = ShellTool(Path(tmp), 'echo')
            # Python is denied in production; inject a controllable child only for cleanup testing.
            with patch.object(tool, 'validate', return_value=[sys.executable, '-c',
                    'import os,time;open("pid", "w").write(str(os.getpid()));time.sleep(60)']):
                pending = asyncio.create_task(tool.execute({'argv': ['echo']}))
                for _ in range(100):
                    if (Path(tmp) / 'pid').exists(): break
                    await asyncio.sleep(0.01)
                self.assertTrue((Path(tmp) / 'pid').exists())
                pid = int((Path(tmp) / 'pid').read_text())
                pending.cancel()
                with self.assertRaises(asyncio.CancelledError): await pending
                with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    async def test_shell_environment_has_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = ShellTool(Path(tmp), 'echo')
            with patch.dict('os.environ', {'TEST_AGENT_SECRET': 'sensitive'}), patch.object(tool, 'validate', return_value=[
                    sys.executable, '-c', 'import os;print(os.getenv("TEST_AGENT_SECRET", "absent"))']):
                result = await tool.execute({'argv': ['echo']})
                self.assertEqual(result['stdout'].strip(), 'absent')

    def test_config_bounds(self):
        for value in ({'max_rounds': 0}, {'timeout_seconds': float('inf')}, {'timeout_seconds': 300}, {'max_tool_calls': 0}):
            with self.assertRaises(ValidationError): AgentSettings.model_validate(value)
        with self.assertRaises(RuntimeError): ShellTool(Path('/tmp'), 'sh,python')

    async def test_whitespace_key_is_not_treated_as_configured(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail('Unexpected request'))) as client:
            tool = TavilyTool(client, '  ')
            with self.assertRaises(ToolError) as error:
                await tool.execute({'query': '上海天气'})
            self.assertEqual(error.exception.code, 'tool_not_configured')
            self.assertIn('未配置', tool.definition['function']['description'])
