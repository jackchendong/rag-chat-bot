import json
import math
from datetime import date, datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..domain.agent import Tool, ToolError


class WeatherArgs(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    city: str = Field(min_length=2, max_length=100, description='用户明确的城市，如武汉。地点未知先询问，不猜测。')
    search_name: str | None = Field(default=None, min_length=2, max_length=100,
        description='可选英文/拼音城市名，如 Wuhan；中文匹配不到时使用。')
    country_code: str | None = Field(default=None, pattern=r'^[A-Z]{2}$', description='明确国家的 ISO 两字母代码，如 CN。')
    forecast_date: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$',
        description='可选 YYYY-MM-DD；省略时返回城市当地今天，支持未来 7 天。')

    @field_validator('city', 'search_name')
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and len(value.strip()) < 2:
            raise ValueError('City cannot be blank')
        return value.strip() if value is not None else None

    @field_validator('forecast_date')
    @classmethod
    def valid_date(cls, value: str | None) -> str | None:
        if value is not None:
            date.fromisoformat(value)
        return value


class Location(BaseModel):
    name: str = Field(max_length=100)
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    country_code: str = Field(max_length=2)
    admin1: str = Field(default='', max_length=100)
    timezone: str = Field(max_length=100)


class OpenMeteoWeatherTool(Tool):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    @property
    def definition(self) -> dict[str, Any]:
        return {'type': 'function', 'function': {'name': 'get_weather',
            'description': '联网查询明确城市的当前天气与未来 7 天预报。使用 Open-Meteo，无需 API 密钥，与 Tavily 配置无关。'
                '优先用于天气问题；中文城市建议同时传英文 search_name。返回当地日期、时区、单位和来源。',
            'parameters': WeatherArgs.model_json_schema()}}

    async def get_json(self, url: str, params: dict[str, Any]) -> tuple[dict[str, Any], str]:
        try:
            async with self.client.stream('GET', url, params=params, timeout=10) as response:
                if response.status_code != 200:
                    raise ToolError('weather_unavailable', '天气服务请求失败，请稍后重试')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 128000:
                        raise ToolError('weather_output_limit', '天气服务响应超过大小限制')
                result = json.loads(body)
                if not isinstance(result, dict) or result.get('error'):
                    raise ValueError
                return result, str(response.request.url)
        except (httpx.HTTPError, ValueError, TypeError):
            raise ToolError('weather_unavailable', '无法连接天气服务或响应无效，请检查服务器网络') from None

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = WeatherArgs.model_validate(arguments)
        locations = []
        geocode_url = ''
        for name in dict.fromkeys(filter(None, (args.city, args.search_name))):
            params: dict[str, Any] = {'name': name, 'count': 5, 'language': 'zh', 'format': 'json'}
            if args.country_code:
                params['countryCode'] = args.country_code
            data, geocode_url = await self.get_json('https://geocoding-api.open-meteo.com/v1/search', params)
            rows = data.get('results', [])
            if not isinstance(rows, list):
                raise ToolError('weather_unavailable', '城市查询响应格式无效')
            try:
                locations = [Location.model_validate(row) for row in rows[:5]]
            except ValidationError:
                raise ToolError('weather_unavailable', '城市查询返回了无效的位置数据') from None
            if locations:
                break
        if not locations:
            raise ToolError('location_not_found', '未找到该城市，可补充省份/国家或英文城市名再查询')
        if len(locations) > 1:
            return {'ok': False, 'error': {'code': 'ambiguous_location', 'message': '找到多个地点，请先确认省份或国家'},
                    'candidates': [item.model_dump() for item in locations]}
        location = locations[0]
        current_fields = ('temperature_2m', 'relative_humidity_2m', 'apparent_temperature', 'weather_code',
                          'wind_speed_10m', 'precipitation')
        daily_fields = ('weather_code', 'temperature_2m_max', 'temperature_2m_min', 'precipitation_probability_max')
        data, source_url = await self.get_json('https://api.open-meteo.com/v1/forecast', {
            'latitude': location.latitude, 'longitude': location.longitude,
            'current': ','.join(current_fields), 'daily': ','.join(daily_fields),
            'timezone': location.timezone, 'forecast_days': 7,
        })
        daily = data.get('daily')
        current = data.get('current')
        if not isinstance(daily, dict) or not isinstance(current, dict) or not isinstance(daily.get('time'), list) or not daily['time']:
            raise ToolError('weather_unavailable', '天气服务未返回日期和天气数据')
        try:
            for day in daily['time']:
                date.fromisoformat(day)
            datetime.fromisoformat(current['time'])
        except (ValueError, TypeError, KeyError):
            raise ToolError('weather_unavailable', '天气服务返回了无效时间') from None
        target = args.forecast_date or daily['time'][0]
        if target not in daily['time']:
            raise ToolError('weather_date_out_of_range', '日期超出当前未来 7 天预报范围，不可当作历史实况查询')
        index = daily['time'].index(target)
        values = {}
        for field in daily_fields:
            series = daily.get(field)
            if not isinstance(series, list) or len(series) <= index:
                raise ToolError('weather_unavailable', '天气服务返回了不完整的预报')
            values[field] = series[index]
        for value in (*values.values(), *(current.get(field) for field in current_fields)):
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ToolError('weather_unavailable', '天气服务返回了无效数值')
        if values['temperature_2m_max'] is None or values['temperature_2m_min'] is None:
            raise ToolError('weather_unavailable', '天气服务未返回温度预报')
        units = data.get('daily_units', {})
        current_units = data.get('current_units', {})
        if not isinstance(units, dict) or not isinstance(current_units, dict):
            raise ToolError('weather_unavailable', '天气服务返回单位格式无效')
        return {'ok': True, 'location': location.model_dump(), 'date': target, 'timezone': location.timezone,
            'current': {key: current.get(key) for key in ('time', *current_fields)} if target == daily['time'][0] else None,
            'current_units': {key: current_units.get(key) for key in current_fields},
            'daily': values, 'daily_units': {key: units.get(key) for key in daily_fields},
            'fetched_at': datetime.now(timezone.utc).isoformat(),
            'sources': [{'title': 'Open-Meteo Weather Forecast', 'url': source_url},
                        {'title': 'Open-Meteo Geocoding', 'url': geocode_url}],
            'weather_code_reference': 'https://open-meteo.com/en/docs#weather-variable-documentation',
            'note': '当前条件和预报来源于天气模型，不是当地气象站实测；时间使用该城市时区。'}
