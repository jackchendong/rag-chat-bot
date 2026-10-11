import unittest
from sqlalchemy import DateTime, DefaultClause, Integer, MetaData, create_engine, text
from sqlalchemy.dialects.mysql import BIGINT, DATETIME
from sqlalchemy.orm import sessionmaker
from backend.db.base import Base
from backend.models import User
from backend.domain.errors import ConversationError
from backend.repositories.conversations import ConversationRepository
from backend.repositories.agent_tasks import AgentTaskRepository


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        metadata = MetaData()
        # Test-only DDL compatibility; production MySQL metadata stays untouched.
        for table in Base.metadata.sorted_tables:
            copied = table.to_metadata(metadata)
            for column in copied.columns:
                if isinstance(column.type, BIGINT): column.type = Integer()
                if isinstance(column.type, DATETIME): column.type = DateTime()
                if column.name in ('created_at', 'updated_at'): column.server_default = DefaultClause(text('CURRENT_TIMESTAMP'))
        metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions() as session:
            session.add_all([User(id=1, account='one'), User(id=2, account='two')])
            session.commit()
        self.conversations = ConversationRepository(self.sessions)
        self.repo = AgentTaskRepository(self.sessions)
        self.conversation = self.conversations.create_conversation(1)
        self.turn = self.conversations.prepare_turn(1, self.conversation.conversation_id, 'test')
        self.task = self.repo.start(self.turn, 'mock', {'policy': {'max_rounds': 6}})

    def tearDown(self): self.engine.dispose()

    def test_sequence_counts_terminal_idempotence(self):
        a = self.repo.begin_step(self.task, 1, 'model', 'mock', {'messages': []})
        self.repo.end_step(a, 'completed', {'tool_calls': []})
        b = self.repo.begin_step(self.task, 1, 'tool', 'shell_exec', {'arguments': '{}'}, 'call')
        self.repo.end_step(b, 'failed', {'ok': False})
        self.repo.finish(self.task, 'completed', 'result')
        self.repo.finish(self.task, 'cancelled', '')
        result = self.repo.detail(1, self.task, 0, 10)
        self.assertEqual(result['task']['output_text'], 'result')
        self.assertEqual(result['task']['round_count'], 1)
        self.assertEqual(result['task']['tool_call_count'], 1)
        self.assertEqual(result['task']['assistant_message_id'], self.turn.assistant_message_id)
        self.assertEqual([step['step_no'] for step in result['steps']], [1, 2])
        self.assertTrue(all(step['duration_ms'] >= 0 for step in result['steps']))
        self.assertEqual(len(self.repo.detail(1, self.task, 1, 1)['steps']), 1)

    def test_foreign_user_cannot_read_task(self):
        self.assertEqual(self.repo.list_tasks(2, None, 0, 10), [])
        with self.assertRaises(ConversationError): self.repo.detail(2, self.task, 0, 10)
        with self.assertRaises(ConversationError): self.repo.list_tasks(2, self.conversation.conversation_id, 0, 10)

    def test_finish_closes_open_step_and_respects_stop(self):
        self.repo.begin_step(self.task, 1, 'tool', 'shell_exec', {}, 'call')
        self.conversations.stop_turn(1, self.conversation.conversation_id, int(self.turn.assistant_message_id))
        status = self.conversations.finish_turn(self.turn, 'partial', 'completed')
        self.repo.finish(self.task, status, 'partial')
        result = self.repo.detail(1, self.task, 0, 10)
        self.assertEqual(result['task']['status'], 'cancelled')
        self.assertEqual(result['steps'][0]['status'], 'cancelled')
        self.assertEqual(result['task']['output_text'], 'partial')
