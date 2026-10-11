import asyncio
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from backend.domain.agent import AgentPolicy, AgentTaskStore, SkillSource, Tool, ToolError
from backend.domain.chat import ModelChunk, ModelGateway, ToolCall
from backend.domain.conversations import ConversationStore, PreparedTurn
from backend.domain.chat import ModelMessage
from backend.services.chat import ChatService
from backend.tools.registry import ToolRegistry
from backend.tools.skills import FileSkillSource, LoadSkillTool
from backend.tools.shell import ShellTool


class MemoryStore(ConversationStore):
    def __init__(self):
        self.cancelled = False
        self.saved = []
    def prepare_turn(self, user_id, conversation_id, message):
        return PreparedTurn(conversation_id, '1', '2', [ModelMessage('user', message)])
    def finish_turn(self, turn, content, status):
        status = 'cancelled' if self.cancelled else status
        self.saved.append((content, status))
        return status
    def is_turn_cancelled(self, turn): return self.cancelled
    def stop_turn(self, *args): self.cancelled = True; return True
    def login(self, account): raise NotImplementedError
    def get_user(self, user_id): raise NotImplementedError
    def create_conversation(self, user_id): raise NotImplementedError
    def list_conversations(self, *args): raise NotImplementedError
    def list_messages(self, *args): raise NotImplementedError


class MemoryTasks(AgentTaskStore):
    def __init__(self): self.steps = []; self.finished = []; self.snapshot = None
    def start(self, turn, model, settings): self.snapshot = settings; return 'task'
    def begin_step(self, task_id, round_no, kind, name, input_data, tool_call_id=None):
        self.steps.append({'round': round_no, 'kind': kind, 'name': name, 'input': input_data, 'status': 'running'})
        return len(self.steps)
    def end_step(self, step_id, status, output): self.steps[step_id - 1].update(status=status, output=output)
    def finish(self, task_id, status, output, error=None): self.finished.append((status, output, error))
    def list_tasks(self, *args): return []
    def detail(self, *args): return {}


class NoSkills(SkillSource):
    def catalog(self): return []
    def load(self, name): raise ToolError('invalid_skill', 'missing')


class Gateway(ModelGateway):
    def __init__(self, rounds): self.rounds = rounds; self.requests = []; self.closed = 0
    async def stream_answer(self, messages, tools=None):
        index = len(self.requests)
        self.requests.append((list(messages), tools))
        try:
            for chunk in self.rounds[index]: yield chunk
        finally: self.closed += 1


class CountingTool(Tool):
    def __init__(self): self.calls = 0; self.started = asyncio.Event(); self.closed = False; self.block = False
    @property
    def definition(self): return {'type': 'function', 'function': {'name': 'test', 'parameters': {'type': 'object'}}}
    async def execute(self, args):
        self.calls += 1; self.started.set()
        try:
            if self.block: await asyncio.Event().wait()
            return {'ok': True, 'value': 42}
        finally: self.closed = True


def tool_chunk(call_id='call', arguments='{}', name='test'):
    return ModelChunk(done=True, finish_reason='tool_calls', tool_calls=(ToolCall(call_id, name, arguments),))


class AgentTests(unittest.IsolatedAsyncioTestCase):
    def service(self, gateway, tool=None, policy=None):
        self.store, self.tasks = MemoryStore(), MemoryTasks()
        self.tool = tool or CountingTool()
        return ChatService(gateway, self.store, self.tasks, ToolRegistry([self.tool]), NoSkills(),
                           policy or AgentPolicy(stop_poll_seconds=0.01), 'test-model')

    async def collect(self, service):
        run = await service.prepare(1, 'conv', 'hello')
        return [event async for event in service.answer(run)]

    async def test_loop_pairs_tool_results_and_records_steps(self):
        gateway = Gateway([[tool_chunk()], [ModelChunk(content='answer'), ModelChunk(done=True, finish_reason='stop')]])
        service = self.service(gateway)
        events = await self.collect(service)
        messages = gateway.requests[1][0]
        self.assertEqual(messages[-2].tool_calls[0].id, messages[-1].tool_call_id)
        self.assertEqual(messages[-1].role, 'tool')
        self.assertEqual(json.loads(messages[-1].content)['value'], 42)
        self.assertEqual([step['kind'] for step in self.tasks.steps], ['model', 'tool', 'model'])
        self.assertTrue(all(step['status'] == 'completed' for step in self.tasks.steps))
        self.assertEqual(events[-1].event, 'done')
        self.assertEqual(self.tasks.finished[-1][:2], ('completed', 'answer'))

    async def test_invalid_json_never_executes_and_model_gets_error(self):
        gateway = Gateway([[tool_chunk(arguments='{')], [ModelChunk(done=True, finish_reason='stop')]])
        await self.collect(self.service(gateway))
        self.assertEqual(self.tool.calls, 0)
        self.assertEqual(self.tasks.steps[1]['status'], 'failed')
        self.assertEqual(json.loads(gateway.requests[1][0][-1].content)['error']['code'], 'invalid_arguments')

    async def test_duplicate_id_never_repeats_side_effect(self):
        service = self.service(Gateway([[tool_chunk()], [tool_chunk()]]))
        events = await self.collect(service)
        self.assertEqual(self.tool.calls, 1)
        self.assertEqual(events[-1].data['code'], 'duplicate_tool_call')
        self.assertEqual(self.tasks.finished[-1][0], 'failed')

    async def test_last_round_disables_tools_and_bounds_loop(self):
        gateway = Gateway([[tool_chunk()], [tool_chunk('again')]])
        events = await self.collect(self.service(gateway, policy=AgentPolicy(max_rounds=2)))
        self.assertEqual(gateway.requests[-1][1], [])
        self.assertEqual(self.tool.calls, 1)
        self.assertEqual(events[-1].data['code'], 'agent_limit')

    async def test_stop_cancels_tool_and_preserves_trace(self):
        tool = CountingTool(); tool.block = True
        service = self.service(Gateway([[tool_chunk()]]), tool)
        run = await service.prepare(1, 'conv', 'hi')
        async def consume(): return [event async for event in service.answer(run)]
        pending = asyncio.create_task(consume())
        await asyncio.wait_for(tool.started.wait(), 1)
        await service.stop(1, 'conv', 2)
        events = await asyncio.wait_for(pending, 1)
        self.assertTrue(tool.closed)
        self.assertEqual(self.tasks.steps[-1]['status'], 'cancelled')
        self.assertTrue(events[-1].data['cancelled'])
        self.assertEqual(self.tasks.finished[-1][0], 'cancelled')

    async def test_model_stop_closes_upstream(self):
        started, closed = asyncio.Event(), asyncio.Event()
        class BlockingGateway(ModelGateway):
            async def stream_answer(self, messages, tools=None):
                try:
                    yield ModelChunk(content='partial')
                    started.set()
                    await asyncio.Event().wait()
                finally: closed.set()
        service = self.service(BlockingGateway())
        run = await service.prepare(1, 'conv', 'hi')
        async def consume(): return [event async for event in service.answer(run)]
        pending = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), 1)
        await service.stop(1, 'conv', 2)
        events = await asyncio.wait_for(pending, 1)
        self.assertTrue(closed.is_set())
        self.assertEqual(self.store.saved[-1], ('partial', 'cancelled'))
        self.assertTrue(events[-1].data['cancelled'])

    async def test_disconnect_cleans_active_tool(self):
        tool = CountingTool(); tool.block = True
        service = self.service(Gateway([[tool_chunk()]]), tool)
        run = await service.prepare(1, 'conv', 'hi')
        async def consume(): return [event async for event in service.answer(run)]
        pending = asyncio.create_task(consume())
        await asyncio.wait_for(tool.started.wait(), 1)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertTrue(tool.closed)
        self.assertEqual(self.tasks.finished[-1][0], 'cancelled')

    async def test_tool_timeout_is_audited_and_returned_to_model(self):
        tool = CountingTool(); tool.block = True
        gateway = Gateway([[tool_chunk()], [ModelChunk(done=True, finish_reason='stop')]])
        await self.collect(self.service(gateway, tool, AgentPolicy(tool_timeout_seconds=0.01)))
        self.assertTrue(tool.closed)
        self.assertEqual(self.tasks.steps[1]['output']['error']['code'], 'tool_timeout')

    async def test_total_deadline_cancels_tool(self):
        tool = CountingTool(); tool.block = True
        events = await self.collect(self.service(Gateway([[tool_chunk()]]), tool,
            AgentPolicy(timeout_seconds=0.03, tool_timeout_seconds=1, stop_poll_seconds=0.005)))
        self.assertTrue(tool.closed)
        self.assertEqual(events[-1].data['code'], 'agent_timeout')

    async def test_tool_budget_rejects_whole_batch(self):
        calls = (ToolCall('a', 'test', '{}'), ToolCall('b', 'test', '{}'))
        events = await self.collect(self.service(Gateway([[ModelChunk(done=True, tool_calls=calls)]]),
            policy=AgentPolicy(max_tool_calls=1)))
        self.assertEqual(self.tool.calls, 0)
        self.assertEqual(events[-1].data['code'], 'agent_limit')

    async def test_disabled_agent_has_no_tools(self):
        gateway = Gateway([[ModelChunk(done=True, finish_reason='stop')]])
        await self.collect(self.service(gateway, policy=AgentPolicy(enabled=False)))
        self.assertEqual(gateway.requests[0][1], [])
        self.assertEqual(gateway.requests[0][0][0].role, 'user')

    async def test_skill_loading_and_path_escape(self):
        root = Path(__file__).resolve().parents[1] / 'skills'
        source = FileSkillSource(root)
        result = await LoadSkillTool(source).execute({'name': 'web-research'})
        self.assertEqual(len(result['sha256']), 64)
        self.assertIn('web_search', result['content'])
        with self.assertRaises(ToolError): source.load('../.env')
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'escape').symlink_to(root / 'web-research', target_is_directory=True)
            with self.assertRaises(ToolError): FileSkillSource(Path(tmp)).load('escape')

    async def test_shell_is_literal_and_path_restricted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = ShellTool(Path(tmp), 'echo,ls,pwd')
            result = await tool.execute({'argv': ['echo', '$(cat ../.env);touch bad']})
            self.assertIn('$(cat ../.env);touch bad', result['stdout'])
            self.assertFalse((Path(tmp) / 'bad').exists())
            for argv in (['ls', '../'], ['ls', '/'], ['ls', '-R'], ['sh', '-c', 'pwd']):
                with self.assertRaises(ToolError): await tool.execute({'argv': argv})
            self.assertEqual((await tool.execute({'argv': ['pwd']}))['exit_code'], 0)

    async def test_output_limit_preserves_valid_json(self):
        service = self.service(Gateway([]), policy=AgentPolicy(max_tool_output_chars=1000))
        result, encoded = service.bound_result({'ok': True, 'text': '"\\' * 2000})
        self.assertLessEqual(len(encoded), 1000)
        self.assertEqual(json.loads(encoded), result)
        self.assertTrue(result['truncated'])

    async def test_prepare_audit_failure_releases_message_marker(self):
        from unittest.mock import patch
        from backend.domain.errors import ConversationError
        service = self.service(Gateway([]))
        with patch.object(self.tasks, 'start', side_effect=ConversationError('storage_unavailable', 'missing table')):
            with self.assertRaises(ConversationError): await service.prepare(1, 'conv', 'hi')
        self.assertEqual(self.store.saved[-1], ('', 'cancelled'))

    async def test_truncated_model_result_keeps_full_bounded_audit(self):
        class LargeTool(CountingTool):
            async def execute(self, args): return {'ok': True, 'content': 'A' * 4000}
        gateway = Gateway([[tool_chunk()], [ModelChunk(done=True, finish_reason='stop')]])
        await self.collect(self.service(gateway, LargeTool(), AgentPolicy(max_tool_output_chars=1000)))
        output = self.tasks.steps[1]['output']
        self.assertEqual(len(output['result']['content']), 4000)
        self.assertTrue(output['model_result']['truncated'])
        self.assertLessEqual(len(gateway.requests[1][0][-1].content), 1000)

    async def test_unexpected_tool_error_is_not_reported_as_cancelled(self):
        class BrokenTool(CountingTool):
            async def execute(self, args): raise RuntimeError('private provider detail')
        gateway = Gateway([[tool_chunk()], [ModelChunk(done=True, finish_reason='stop')]])
        with self.assertLogs('backend.tools.registry', level='ERROR'):
            events = await self.collect(self.service(gateway, BrokenTool()))
        self.assertEqual(self.tasks.steps[1]['status'], 'failed')
        self.assertEqual(self.tasks.steps[1]['output']['error']['code'], 'tool_failed')
        self.assertNotIn('private provider detail', gateway.requests[1][0][-1].content)
        self.assertFalse(events[-1].data['cancelled'])

    async def test_unconfigured_web_is_audited_as_configuration_error(self):
        import httpx
        from backend.tools.web import TavilyTool
        gateway = Gateway([[tool_chunk(name='web_search', arguments='{"query":"上海今日天气"}')],
                           [ModelChunk(content='联网服务尚未配置'), ModelChunk(done=True, finish_reason='stop')]])
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: self.fail('No key: no HTTP call'))) as client:
            service = self.service(gateway, TavilyTool(client, ''))
            events = await self.collect(service)
        tool_result = json.loads(gateway.requests[1][0][-1].content)
        self.assertEqual(tool_result['error']['code'], 'tool_not_configured')
        self.assertEqual(self.tasks.steps[1]['name'], 'web_search')
        self.assertEqual(self.tasks.steps[1]['status'], 'failed')
        self.assertEqual(events[-1].event, 'done')
        self.assertIn('tool_not_configured', gateway.requests[0][1][0]['function']['description'])
