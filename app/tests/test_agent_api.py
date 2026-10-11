import unittest

import httpx

from backend.application import create_app
from backend.domain.conversations import UserInfo
from backend.domain.chat import ModelChunk
from backend.domain.errors import ConversationError
from backend.domain.agent import AgentPolicy
from backend.services.chat import ChatService
from backend.tools.registry import ToolRegistry
from test_agent import MemoryStore, MemoryTasks, NoSkills, Gateway, CountingTool


class UserStore(MemoryStore):
    def get_user(self, user_id):
        if user_id != 1: raise ConversationError('invalid_user', 'missing')
        return UserInfo('1', 'test')


class AgentAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = create_app()
        self.app.state.conversation_store = UserStore()
        self.app.state.chat_service = ChatService(
            Gateway([[ModelChunk(content='answer'), ModelChunk(done=True, finish_reason='stop')]]),
            self.app.state.conversation_store, MemoryTasks(), ToolRegistry([CountingTool()]),
            NoSkills(), AgentPolicy(), 'mock')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self): await self.client.aclose()

    async def test_routes_require_existing_user_and_validate_paging(self):
        for path in ('/api/skills', '/api/agent/tasks', '/api/agent/tasks/00000000-0000-0000-0000-000000000001'):
            self.assertEqual((await self.client.get(path)).status_code, 401)
            self.assertEqual((await self.client.get(path, headers={'X-User-Id': '2'})).status_code, 401)
        self.assertEqual((await self.client.get('/api/skills', headers={'X-User-Id': '1'})).status_code, 200)
        self.assertEqual((await self.client.get('/api/agent/tasks?limit=101', headers={'X-User-Id': '1'})).status_code, 422)

    async def test_chat_keeps_existing_events_and_adds_task_id(self):
        response = await self.client.post('/api/chat', headers={'X-User-Id': '1'}, json={
            'conversation_id': '00000000-0000-0000-0000-000000000001', 'message': 'hi'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/event-stream', response.headers['content-type'])
        self.assertIn('"task_id": "task"', response.text)
        self.assertIn('event: message', response.text)
        self.assertIn('event: done', response.text)
        self.assertNotIn('event: error', response.text)

    async def test_invalid_skill_fails_before_preparing_turn(self):
        response = await self.client.post('/api/chat', headers={'X-User-Id': '1'}, json={
            'conversation_id': '00000000-0000-0000-0000-000000000001', 'message': 'hi', 'skill_names': ['missing']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_skill')
        self.assertIsNone(self.app.state.chat_service.tasks.snapshot)
