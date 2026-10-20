from datetime import datetime, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    prompt: str = Field(min_length=1, max_length=10000)
    kind: Literal['once', 'cron']
    timezone: str = Field(min_length=1, max_length=64)
    cron: str | None = Field(default=None, max_length=120)
    run_at: datetime | None = None

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('请提供有效的 IANA 时区') from None
        return value

    @model_validator(mode='after')
    def valid_schedule(self) -> 'ScheduleInput':
        if self.kind == 'once':
            if self.cron is not None or self.run_at is None or self.run_at.utcoffset() is None:
                raise ValueError('一次性任务需要带时区的 run_at，不能设置 cron')
        else:
            if self.run_at is not None or not self.cron:
                raise ValueError('周期任务需要五段 cron，不能设置 run_at')
            try:
                trigger = CronTrigger.from_crontab(self.cron, timezone=ZoneInfo(self.timezone))
                if trigger.get_next_fire_time(None, datetime.now(timezone.utc)) is None:
                    raise ValueError('计划没有未来执行时间')
            except (ValueError, KeyError):
                raise ValueError('cron 无效或没有未来执行时间') from None
        return self


class CreateSchedule(ScheduleInput):
    conversation_id: UUID
    request_id: UUID


class ScheduleState(BaseModel):
    status: Literal['active', 'paused']


class RunNow(BaseModel):
    request_id: UUID
