import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import httpx
from pydantic import ValidationError
from sqlalchemy import DateTime, DefaultClause, Integer, MetaData, create_engine, select, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import sessionmaker

from backend.application import create_app
from backend.db.base import Base
from backend.domain.agent import AgentPolicy, ToolContext, ToolError
from backend.domain.chat import ModelChunk, ToolCall
from backend.domain.errors import ConversationError
from backend.models import Conversation, Message, ScheduledRun, ScheduledTask, User
from backend.repositories.agent_tasks import AgentTaskRepository
from backend.repositories.conversations import ConversationRepository, utc_now
from backend.repositories.schedules import ScheduleRepository, next_fire
from backend.schemas.schedule import ScheduleInput
from backend.services.chat import ChatService
from backend.services.schedules import ScheduleRunner
from backend.tools.registry import ToolRegistry
from backend.tools.schedules import CreateScheduledTaskTool
from backend.tools.skills import FileSkillSource, LoadSkillTool
from test_agent import Gateway, NoSkills


class ScheduleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + (Path(self.temp.name) / 'schedules.db').as_posix(),
                                    connect_args={'check_same_thread': False})
        metadata = MetaData()
        for table in Base.metadata.sorted_tables:
            copied = table.to_metadata(metadata)
            for column in copied.columns:
                if isinstance(column.type, BIGINT):
                    column.type = Integer()
                if isinstance(column.type, DATETIME):
                    column.type = DateTime()
                if column.name in ('created_at', 'updated_at'):
                    column.server_default = DefaultClause(text('CURRENT_TIMESTAMP'))
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions() as session:
            session.add_all([User(id=1, account='one'), User(id=2, account='two')])
            session.commit()
        self.conversations = ConversationRepository(self.sessions)
        self.conv = self.conversations.create_conversation(1).conversation_id
        self.repo = ScheduleRepository(self.sessions)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def create(self, **overrides):
        data = dict(name='daily', prompt='生成学习建议', kind='cron', timezone='Asia/Shanghai',
                    cron='0 9 * * *', run_at=None, conversation_id=self.conv, request_id=str(uuid4()))
        data.update(overrides)
        return self.repo.save(1, data)

    def service(self, gateway=None):
        return ChatService(gateway or Gateway([[ModelChunk(content='定时执行结果'),
            ModelChunk(done=True, finish_reason='stop')]]), self.conversations,
            AgentTaskRepository(self.sessions), ToolRegistry([]), NoSkills(), AgentPolicy(), 'mock')

    def agent_service(self, gateway, policy=None):
        skills = FileSkillSource(Path(__file__).resolve().parents[1] / 'skills')
        return ChatService(gateway, self.conversations, AgentTaskRepository(self.sessions),
            ToolRegistry([LoadSkillTool(skills), CreateScheduledTaskTool(self.repo)]),
            skills, policy or AgentPolicy(), 'mock')

    def create_arguments(self):
        return dict(name='武汉天气', prompt='查询武汉今天的天气，给出温度和降水建议',
                    kind='cron', timezone='Asia/Shanghai', cron='0 9 * * *', run_at=None)

    async def test_chat_function_call_loads_skill_and_persists_ai_extracted_task(self):
        arguments = self.create_arguments()
        gateway = Gateway([
            [ModelChunk(done=True, tool_calls=(ToolCall('skill', 'load_skill', '{"name":"scheduled-tasks"}'),))],
            [ModelChunk(done=True, tool_calls=(ToolCall('create', 'create_scheduled_task', json.dumps(arguments)),))],
            [ModelChunk(content='已创建武汉天气任务，每天北京时间09:00执行。'), ModelChunk(done=True, finish_reason='stop')],
        ])
        app = create_app()
        app.state.conversation_store = self.conversations
        app.state.chat_service = self.agent_service(gateway)
        app.state.schedule_store = self.repo
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/chat', headers={'X-User-Id': '1'}, json={
                'conversation_id': self.conv, 'message': '北京时间每天早上9点帮我查武汉天气'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('event: done', response.text)
            self.assertNotIn('event: error', response.text)
            result = (await client.get('/api/scheduled-tasks', headers={'X-User-Id': '1'})).json()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['prompt'], arguments['prompt'])
        self.assertEqual(result[0]['conversation_id'], self.conv)
        self.assertEqual((result[0]['cron'], result[0]['timezone']), ('0 9 * * *', 'Asia/Shanghai'))
        model_result = json.loads(gateway.requests[2][0][-1].content)
        self.assertTrue(model_result['persisted'])
        self.assertEqual(model_result['task']['id'], result[0]['id'])
        audit = app.state.chat_service.tasks.list_tasks(1, self.conv, 0, 20)[0]
        steps = app.state.chat_service.tasks.detail(1, audit['id'], 0, 20)['steps']
        tools = [step for step in steps if step['kind'] == 'tool']
        self.assertEqual([step['name'] for step in tools], ['load_skill', 'create_scheduled_task'])
        self.assertIn('不能把中文等同于北京时间', tools[0]['output_data']['content'])
        self.assertEqual(tools[1]['output_data']['task']['id'], result[0]['id'])

    async def test_chat_clarifies_then_uses_conversation_history(self):
        gateway = Gateway([
            [ModelChunk(content='请问使用哪个时区？'), ModelChunk(done=True, finish_reason='stop')],
            [ModelChunk(done=True, tool_calls=(ToolCall('create', 'create_scheduled_task', json.dumps(self.create_arguments())),))],
            [ModelChunk(content='已创建。'), ModelChunk(done=True, finish_reason='stop')],
        ])
        service = self.agent_service(gateway)
        first = await service.prepare(1, self.conv, '每天早上9点查武汉天气')
        _ = [event async for event in service.answer(first)]
        self.assertEqual(self.repo.list_tasks(1, self.conv, 0, 30), [])
        second = await service.prepare(1, self.conv, '北京时间')
        _ = [event async for event in service.answer(second)]
        self.assertIn('请问使用哪个时区？', [item.content for item in gateway.requests[1][0]])
        self.assertEqual(len(self.repo.list_tasks(1, self.conv, 0, 30)), 1)

    async def test_tool_contexts_are_isolated_and_model_cannot_choose_owner(self):
        other_conv = self.conversations.create_conversation(2).conversation_id
        root = ToolRegistry([CreateScheduledTaskTool(self.repo)])
        first = root.bind(ToolContext(1, self.conv, 'turn-one'))
        second = root.bind(ToolContext(2, other_conv, 'turn-two'))
        arguments = json.dumps(self.create_arguments())
        results = await asyncio.gather(first.execute('create_scheduled_task', arguments),
                                       second.execute('create_scheduled_task', arguments))
        self.assertEqual(results[0]['task']['conversation_id'], self.conv)
        self.assertEqual(results[1]['task']['conversation_id'], other_conv)
        self.assertNotEqual(results[0]['task']['id'], results[1]['task']['id'])
        spoofed = self.create_arguments() | {'user_id': 2, 'conversation_id': other_conv}
        with self.assertRaises(ToolError):
            await first.execute('create_scheduled_task', json.dumps(spoofed))
        with self.assertRaises(ToolError):
            await root.execute('create_scheduled_task', arguments)
        self.assertEqual(len(self.repo.list_tasks(1, None, 0, 30)), 1)
        self.assertEqual(len(self.repo.list_tasks(2, None, 0, 30)), 1)

    async def test_repeated_creation_tool_calls_in_one_turn_are_deduplicated(self):
        tool = ToolRegistry([CreateScheduledTaskTool(self.repo)]).bind(ToolContext(1, self.conv, 'same-turn'))
        args = self.create_arguments()
        result = await tool.execute('create_scheduled_task', json.dumps(args))
        args.update(name='另一个任务名称', cron='0  9 * * *')
        repeated = await tool.execute('create_scheduled_task', json.dumps(args))
        self.assertEqual(result['task']['id'], repeated['task']['id'])
        self.assertEqual(len(self.repo.list_tasks(1, None, 0, 30)), 1)

    async def test_tool_rejects_missing_timezone_and_reports_storage_failure(self):
        tool = ToolRegistry([CreateScheduledTaskTool(self.repo)]).bind(ToolContext(1, self.conv, 'turn'))
        arguments = self.create_arguments()
        del arguments['timezone']
        with self.assertRaises(ToolError) as failure:
            await tool.execute('create_scheduled_task', json.dumps(arguments))
        self.assertEqual(failure.exception.code, 'invalid_arguments')
        with patch.object(self.repo, 'save', side_effect=ConversationError('storage_unavailable', '数据库操作失败')):
            with self.assertRaises(ToolError) as failure:
                await tool.execute('create_scheduled_task', json.dumps(self.create_arguments()))
        self.assertEqual(failure.exception.code, 'storage_unavailable')
        self.assertEqual(self.repo.list_tasks(1, None, 0, 30), [])

    async def test_background_execution_cannot_recursively_create_tasks(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        gateway = Gateway([
            [ModelChunk(done=True, tool_calls=(ToolCall('forged', 'create_scheduled_task', json.dumps(self.create_arguments())),))],
            [ModelChunk(content='执行任务结果。'), ModelChunk(done=True, finish_reason='stop')],
        ])
        runner = ScheduleRunner(self.repo, self.agent_service(gateway))
        await runner.tick()
        await runner.wait()
        self.assertEqual(len(self.repo.list_tasks(1, None, 0, 30)), 1)
        self.assertNotIn('create_scheduled_task', [tool['function']['name'] for tool in gateway.requests[0][1]])
        result = json.loads(gateway.requests[1][0][-1].content)
        self.assertEqual(result['error']['code'], 'unknown_tool')

    async def test_agent_disabled_does_not_expose_creation_function(self):
        gateway = Gateway([[ModelChunk(content='Agent已关闭'), ModelChunk(done=True, finish_reason='stop')]])
        service = self.agent_service(gateway, AgentPolicy(enabled=False))
        run = await service.prepare(1, self.conv, '北京时间每天9点查天气')
        _ = [event async for event in service.answer(run)]
        self.assertEqual(gateway.requests[0][1], [])
        self.assertEqual(self.repo.list_tasks(1, None, 0, 30), [])

    def test_timezone_validation_and_dst(self):
        now = datetime(2026, 10, 19, 0, 0)
        self.assertEqual(next_fire('cron', '0 9 * * *', 'Asia/Shanghai', None, now), datetime(2026, 10, 19, 1))
        # March 8 02:30 does not exist in New York; skip to the next valid day.
        result = next_fire('cron', '30 2 * * *', 'America/New_York', None, datetime(2026, 3, 8, 5))
        self.assertEqual(result, datetime(2026, 3, 9, 6, 30))
        base = dict(name='x', prompt='x', kind='once', timezone='Asia/Shanghai')
        for extra in ({'run_at': '2030-01-01T09:00:00'},
                      {'run_at': '2030-01-01T00:00:00Z', 'timezone': 'invalid/zone'},
                      {'kind': 'cron', 'cron': '* * * * bad'}):
            with self.assertRaises(ValidationError):
                ScheduleInput(**(base | extra))

    def test_persist_pause_edit_and_idempotence(self):
        request_id = str(uuid4())
        task = self.create(request_id=request_id)
        self.assertEqual(self.create(request_id=request_id)['id'], task['id'])
        fresh = ScheduleRepository(self.sessions)
        self.assertEqual(fresh.list_tasks(1, self.conv, 0, 30)[0]['id'], task['id'])
        self.assertIsNone(fresh.set_state(1, task['id'], 'paused')['next_run_at'])
        edited = fresh.save(1, dict(name='edited', prompt='new', kind='cron', timezone='UTC',
                                  cron='0 10 * * *', run_at=None), task['id'])
        self.assertEqual((edited['status'], edited['prompt']), ('paused', 'new'))
        self.assertIsNotNone(fresh.set_state(1, task['id'], 'active')['next_run_at'])
        self.assertEqual(fresh.list_tasks(2, None, 0, 30), [])
        for operation in (lambda: fresh.enqueue(2, task['id'], str(uuid4())),
                          lambda: fresh.set_state(2, task['id'], 'paused'),
                          lambda: fresh.runs(2, task['id'], 0, 20),
                          lambda: fresh.list_tasks(2, self.conv, 0, 30)):
            with self.assertRaises(ConversationError):
                operation()

    async def test_immediate_execution_persists_messages_and_run_links(self):
        task = self.create()
        request_id = str(uuid4())
        first = self.repo.enqueue(1, task['id'], request_id)
        self.assertEqual(self.repo.enqueue(1, task['id'], request_id)['id'], first['id'])
        with self.assertRaises(ConversationError):
            self.repo.enqueue(1, task['id'], str(uuid4()))
        runner = ScheduleRunner(self.repo, self.service())
        await runner.tick()
        await runner.wait()
        records = self.repo.runs(1, task['id'], 0, 20)
        self.assertEqual(records[0]['status'], 'completed')
        messages = self.conversations.list_messages(1, self.conv, None, 50)
        self.assertEqual(messages[-1].content, '定时执行结果')
        self.assertEqual(records[0]['assistant_message_id'], messages[-1].id)
        # Running manually does not move the original calendar schedule.
        self.assertEqual(self.repo.list_tasks(1, None, 0, 30)[0]['next_run_at'], task['next_run_at'])

    async def test_due_once_and_overdue_cron_coalescing(self):
        now = utc_now()
        once = self.create(kind='once', cron=None, run_at=(now + timedelta(hours=1)).replace(tzinfo=timezone.utc))
        with self.sessions() as session:
            session.get(ScheduledTask, once['id']).next_run_at = now - timedelta(hours=1)
            session.commit()
        first = self.repo.claim()
        self.assertIsNotNone(first)
        self.assertIsNone(self.repo.claim())
        await ScheduleRunner(self.repo, self.service()).execute(first)
        state = self.repo.list_tasks(1, None, 0, 30)[0]
        self.assertEqual((state['status'], state['next_run_at']), ('completed', None))
        self.assertEqual(self.repo.runs(1, once['id'], 0, 20)[0]['status'], 'completed')
        cron = self.create()
        with self.sessions() as session:
            session.get(ScheduledTask, cron['id']).next_run_at = now - timedelta(days=7)
            session.commit()
        execution = self.repo.claim()
        self.assertIsNotNone(execution)
        self.assertIsNone(self.repo.claim())
        with self.sessions() as session:
            self.assertGreater(session.get(ScheduledTask, cron['id']).next_run_at, now)

    async def test_recovery_fails_stale_run_and_releases_conversation(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        execution = self.repo.claim()
        service = self.service()
        prepared = await service.prepare(1, self.conv, execution.prompt, scheduled_run_id=execution.run_id)
        with self.sessions() as session:
            session.get(ScheduledRun, execution.run_id).started_at = utc_now() - timedelta(minutes=11)
            session.commit()
        self.repo.recover()
        self.assertEqual(self.repo.runs(1, task['id'], 0, 20)[0]['status'], 'failed')
        with self.sessions() as session:
            self.assertIsNone(session.get(Conversation, self.conv).active_message_id)
            self.assertEqual(session.get(Message, int(prepared.turn.assistant_message_id)).status, 'failed')
        self.repo.finish(execution.run_id, 'completed', None)
        self.assertEqual(self.repo.runs(1, task['id'], 0, 20)[0]['status'], 'failed')

    async def test_failure_before_prepare_still_has_conversation_record(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        service = self.service()
        async def fail(*args, **kwargs):
            raise ConversationError('conversation_busy', '当前会话忙')
        with patch.object(service, 'prepare', fail):
            runner = ScheduleRunner(self.repo, service)
            await runner.tick()
            await runner.wait()
        record = self.repo.runs(1, task['id'], 0, 20)[0]
        self.assertEqual(record['status'], 'failed')
        self.assertIsNotNone(record['assistant_message_id'])
        self.assertIn('当前会话忙', self.conversations.list_messages(1, self.conv, None, 50)[-1].content)

    async def test_recovery_preserves_result_committed_before_process_exit(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        execution = self.repo.claim()
        service = self.service()
        prepared = await service.prepare(1, self.conv, execution.prompt, scheduled_run_id=execution.run_id)
        events = [event async for event in service.answer(prepared)]
        self.assertEqual(events[-1].event, 'done')
        # Simulate a crash after the answer commit and before ScheduleRepository.finish.
        self.repo.recover()
        self.assertEqual(self.repo.runs(1, task['id'], 0, 20)[0]['status'], 'completed')

    async def test_failed_worker_closes_linked_message_and_releases_conversation(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        service = self.service()
        with patch.object(service, 'answer', side_effect=RuntimeError('test failure')):
            runner = ScheduleRunner(self.repo, service)
            await runner.tick()
            await runner.wait()
        row = self.repo.runs(1, task['id'], 0, 20)[0]
        self.assertEqual(row['status'], 'failed')
        messages = self.conversations.list_messages(1, self.conv, None, 50)
        self.assertEqual(messages[-1].status, 'failed')
        self.assertIn('执行异常', messages[-1].content)
        with self.sessions() as session:
            self.assertIsNone(session.get(Conversation, self.conv).active_message_id)

    async def test_run_records_include_persisted_result_preview(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        runner = ScheduleRunner(self.repo, self.service())
        await runner.tick()
        await runner.wait()
        row = self.repo.runs(1, task['id'], 0, 20)[0]
        self.assertEqual(row['result_preview'], '定时执行结果')
        self.assertEqual(row['message_status'], 'completed')
        self.assertFalse(row['result_truncated'])

    async def test_busy_conversation_defers_and_model_failure_is_recorded(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        turn = self.conversations.prepare_turn(1, self.conv, 'ordinary chat')
        self.assertIsNone(self.repo.claim())
        self.conversations.finish_turn(turn, 'done', 'completed')
        runner = ScheduleRunner(self.repo, self.service(Gateway([[]])))
        await runner.tick()
        await runner.wait()
        self.assertEqual(self.repo.runs(1, task['id'], 0, 20)[0]['status'], 'failed')

    async def test_shutdown_cancels_owned_worker_and_saves_terminal_states(self):
        started = asyncio.Event()
        class BlockingGateway(Gateway):
            async def stream_answer(self, messages, tools=None):
                started.set()
                await asyncio.Event().wait()
                yield ModelChunk(done=True)
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        runner = ScheduleRunner(self.repo, self.service(BlockingGateway([])))
        await runner.tick()
        await asyncio.wait_for(started.wait(), timeout=5)
        await runner.close()
        self.assertFalse(runner.workers)
        self.assertEqual(self.repo.runs(1, task['id'], 0, 20)[0]['status'], 'cancelled')
        self.assertEqual(self.conversations.list_messages(1, self.conv, None, 50)[-1].status, 'cancelled')

    async def test_preparation_has_a_timeout_and_does_not_leave_running_record(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        execution = self.repo.claim()
        service = self.service()
        service.policy = AgentPolicy(timeout_seconds=0.05)
        async def blocked_prepare(*args, **kwargs):
            await asyncio.Event().wait()
        with patch.object(service, 'prepare', blocked_prepare):
            await asyncio.wait_for(ScheduleRunner(self.repo, service).execute(execution), timeout=3)
        row = self.repo.runs(1, task['id'], 0, 20)[0]
        self.assertEqual(row['status'], 'failed')
        self.assertIn('超过总时间限制', row['error'])
        self.assertEqual(row['message_status'], 'failed')
        self.assertIsNotNone(row['finished_at'])

    async def test_transient_result_write_failure_is_retried_without_model_replay(self):
        task = self.create()
        self.repo.enqueue(1, task['id'], str(uuid4()))
        service = self.service()
        original_finish = self.repo.finish
        attempts = []
        def flaky_finish(*args):
            attempts.append(args)
            if len(attempts) == 1:
                raise ConversationError('storage_unavailable', '临时故障')
            return original_finish(*args)
        with patch.object(self.repo, 'finish', flaky_finish):
            runner = ScheduleRunner(self.repo, service)
            await runner.tick()
            await runner.wait()
        row = self.repo.runs(1, task['id'], 0, 20)[0]
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(service.gateway.requests), 1)
        self.assertEqual(row['result_preview'], '定时执行结果')

    async def test_running_result_and_final_result_are_visible_through_api(self):
        started, release = asyncio.Event(), asyncio.Event()
        class DelayedGateway(Gateway):
            async def stream_answer(self, messages, tools=None):
                started.set()
                await release.wait()
                yield ModelChunk(content='已完成的后台结果')
                yield ModelChunk(done=True, finish_reason='stop')
        task = self.create()
        queued = self.repo.enqueue(1, task['id'], str(uuid4()))
        runner = ScheduleRunner(self.repo, self.service(DelayedGateway([])))
        app = create_app()
        app.state.conversation_store, app.state.schedule_store = self.conversations, self.repo
        try:
            await runner.tick()
            await asyncio.wait_for(started.wait(), timeout=5)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                url = f"/api/scheduled-tasks/{task['id']}/runs"
                headers = {'X-User-Id': '1'}
                running = (await client.get(url, headers=headers)).json()[0]
                self.assertEqual((running['id'], running['status'], running['message_status']),
                                 (queued['id'], 'running', 'generating'))
                release.set()
                await asyncio.wait_for(runner.wait(), timeout=5)
                complete = (await client.get(url, headers=headers)).json()[0]
                self.assertEqual(complete['status'], 'completed')
                self.assertEqual(complete['result_preview'], '已完成的后台结果')
                self.assertIsNotNone(complete['finished_at'])
                messages = (await client.get(f'/api/conversations/{self.conv}/messages', headers=headers)).json()
                self.assertEqual(messages[-1]['id'], complete['assistant_message_id'])
                self.assertEqual(messages[-1]['content'], complete['result_preview'])
        finally:
            release.set()
            await runner.close()

    def test_once_retry_after_due_time_returns_existing_task(self):
        request_id = str(uuid4())
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        task = self.create(kind='once', cron=None, run_at=future, request_id=request_id)
        # A lost response can be retried later with the original key and timestamp.
        with patch('backend.repositories.schedules.datetime') as clock:
            clock.now.return_value = future + timedelta(hours=1)
            self.assertEqual(self.create(kind='once', cron=None, run_at=future, request_id=request_id)['id'], task['id'])
        with self.assertRaises(ConversationError):
            self.create(kind='once', cron=None, run_at=datetime(2020, 1, 1, tzinfo=timezone.utc))

    async def test_api_validation_ownership_and_paging(self):
        app = create_app()
        app.state.conversation_store = self.conversations
        app.state.schedule_store = self.repo
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = '/api/scheduled-tasks'
            self.assertEqual((await client.get(url)).status_code, 401)
            payload = dict(name='api', prompt='hello', kind='cron', timezone='Asia/Shanghai',
                           cron='0 9 * * *', conversation_id=self.conv, request_id=str(uuid4()))
            headers = {'X-User-Id': '1'}
            response = await client.post(url, headers=headers, json=payload)
            self.assertEqual(response.status_code, 201, response.text)
            task_id = response.json()['id']
            self.assertEqual((await client.get(url + '?limit=101', headers=headers)).status_code, 422)
            self.assertEqual((await client.get(f'{url}/{task_id}/runs', headers={'X-User-Id': '2'})).status_code, 404)
            response = await client.post(f'{url}/{task_id}/run', headers=headers, json={'request_id': str(uuid4())})
            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()['status'], 'queued')
            response = await client.post(f'{url}/{task_id}/state', headers=headers, json={'status': 'paused'})
            self.assertEqual(response.json()['status'], 'paused')


if __name__ == '__main__':
    unittest.main()
