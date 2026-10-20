import hashlib
import json
from datetime import timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import anyio
from pydantic import Field

from ..domain.agent import Tool, ToolContext, ToolError
from ..domain.errors import ConversationError
from ..domain.schedule import ScheduleCreator
from ..schemas.schedule import ScheduleInput


class CreateScheduledTaskArgs(ScheduleInput):
    name: str = Field(min_length=1, max_length=80, description='从用户意图提取的简短任务名称')
    prompt: str = Field(min_length=1, max_length=10000, description=(
        'AI 提取的独立执行提示词，补齐明确的城市、主题等上下文；例如“查询武汉今天的天气”。'
        '不要包含“每天九点执行”“创建定时任务”等调度指令，不硬编码周期任务今天的日期。'))
    timezone: str = Field(min_length=1, max_length=64, description='用户明确提供或会话已明确的 IANA 时区，如 Asia/Shanghai；缺失先询问')


class CreateScheduledTaskTool(Tool):
    def __init__(self, store: ScheduleCreator, context: ToolContext | None = None) -> None:
        self.store, self.context = store, context

    def bind(self, context: ToolContext) -> Tool | None:
        if context.scheduled_execution:
            return None
        return CreateScheduledTaskTool(self.store, context)

    @property
    def definition(self) -> dict[str, Any]:
        return {'type': 'function', 'function': {
            'name': 'create_scheduled_task',
            'description': (
                '用户要求定时、每天、每周或在指定时刻执行任务时，先加载 scheduled-tasks Skill，'
                '从对话提取任务提示词和计划。内容、准确时间、频率及时区已明确时直接调用并持久化；'
                '信息不明确先追问，不让用户填写表单。kind=cron 使用五段 cron（星期 mon–sun），'
                'kind=once 使用含 UTC 偏移的未来 run_at。只有返回 ok=true 且 persisted=true 才能报告创建成功。'
                '用户与会话由后端绑定，不接受模型传入身份或会话 ID。'),
            'parameters': CreateScheduledTaskArgs.model_json_schema(),
        }}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        context = self.context
        if context is None or context.scheduled_execution or not context.user_message_id:
            raise ToolError('schedule_context_required', '定时任务只能由用户当前对话创建')
        args = CreateScheduledTaskArgs.model_validate(arguments)
        data = args.model_dump()
        if data['cron']:
            data['cron'] = ' '.join(data['cron'].split())
        if data['run_at']:
            data['run_at'] = data['run_at'].astimezone(timezone.utc)
        canonical = {key: value for key, value in data.items() if key != 'name'}
        encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        # A repeated call in one user turn reuses its persisted request key, independently of tool-call IDs.
        data['request_id'] = str(uuid5(NAMESPACE_URL,
            f'schedule:{context.user_id}:{context.conversation_id}:{context.user_message_id}:{digest}'))
        data['conversation_id'] = context.conversation_id
        try:
            with anyio.CancelScope(shield=True):
                task = await anyio.to_thread.run_sync(self.store.save, context.user_id, data)
        except ConversationError as error:
            raise ToolError(error.code, error.message) from None
        return {'ok': True, 'persisted': True, 'task': task}
