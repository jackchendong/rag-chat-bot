import asyncio
import json
import unittest

import httpx

from backend.domain.agent import ToolError
from backend.domain.chat import ModelChunk
from backend.tools.weather import OpenMeteoWeatherTool
import test_agent as agent_fixture
from test_agent import Gateway, tool_chunk

LOCATION = {'name': '武汉', 'country_code': 'CN', 'admin1': '湖北', 'timezone': 'Asia/Shanghai',
            'latitude': 30.58, 'longitude': 114.27}
FORECAST = {'current': {'time': '2026-10-11T10:00', 'temperature_2m': 24, 'weather_code': 3},
            'current_units': {'temperature_2m': '°C', 'weather_code': 'wmo code'},
            'daily': {'time': ['2026-10-11', '2026-10-12'], 'weather_code': [3, 61],
                'temperature_2m_max': [26, 22], 'temperature_2m_min': [19, 18],
                'precipitation_probability_max': [20, 80]},
            'daily_units': {'temperature_2m_max': '°C', 'temperature_2m_min': '°C',
                            'precipitation_probability_max': '%', 'weather_code': 'wmo code'}}


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    def handler(self, request):
        self.requests.append(request)
        self.assertNotIn('Authorization', request.headers)
        if request.url.host == 'geocoding-api.open-meteo.com':
            return httpx.Response(200, json={'results': [LOCATION]})
        self.assertEqual(request.url.host, 'api.open-meteo.com')
        self.assertEqual(request.url.params['timezone'], 'Asia/Shanghai')
        return httpx.Response(200, json=FORECAST)

    async def asyncSetUp(self): self.requests = []

    async def test_today_uses_local_date_and_no_key(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            result = await OpenMeteoWeatherTool(client).execute({'city': '武汉', 'country_code': 'CN'})
        self.assertEqual(result['date'], '2026-10-11')
        self.assertEqual(result['timezone'], 'Asia/Shanghai')
        self.assertEqual(result['daily']['temperature_2m_max'], 26)
        self.assertEqual(result['current']['temperature_2m'], 24)
        self.assertEqual(len(result['sources']), 2)
        self.assertEqual(len(self.requests), 2)

    async def test_forecast_not_mislabelled_as_current(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            result = await OpenMeteoWeatherTool(client).execute({'city': '武汉', 'forecast_date': '2026-10-12'})
        self.assertIsNone(result['current'])
        self.assertEqual(result['daily']['weather_code'], 61)

    async def test_english_fallback_after_no_chinese_match(self):
        def handler(request):
            if request.url.params.get('name') == '武汉':
                self.requests.append(request)
                return httpx.Response(200, json={})
            return self.handler(request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenMeteoWeatherTool(client).execute({'city': '武汉', 'search_name': 'Wuhan'})
        self.assertTrue(result['ok'])
        self.assertEqual(self.requests[1].url.params['name'], 'Wuhan')

    async def test_ambiguous_city_does_not_pick_one(self):
        def handler(request):
            self.assertEqual(request.url.host, 'geocoding-api.open-meteo.com')
            return httpx.Response(200, json={'results': [LOCATION, {**LOCATION, 'admin1': '另一省'}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await OpenMeteoWeatherTool(client).execute({'city': '同名市'})
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'ambiguous_location')
        self.assertEqual(len(result['candidates']), 2)

    async def test_out_of_range_or_missing_city_is_explicit(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            with self.assertRaises(ToolError) as error:
                await OpenMeteoWeatherTool(client).execute({'city': '武汉', 'forecast_date': '2000-01-01'})
            self.assertEqual(error.exception.code, 'weather_date_out_of_range')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as client:
            with self.assertRaises(ToolError) as error: await OpenMeteoWeatherTool(client).execute({'city': '不存在'})
            self.assertEqual(error.exception.code, 'location_not_found')

    async def test_network_failure_has_no_fake_data(self):
        def handler(request): raise httpx.ConnectError('private detail', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ToolError) as error: await OpenMeteoWeatherTool(client).execute({'city': '武汉'})
            self.assertEqual(error.exception.code, 'weather_unavailable')
            self.assertNotIn('private detail', error.exception.message)

    async def test_cancellation_closes_weather_response(self):
        started, closed = asyncio.Event(), asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b'{}'
            async def aclose(self): closed.set()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=Body()))) as client:
            pending = asyncio.create_task(OpenMeteoWeatherTool(client).execute({'city': '武汉'}))
            await asyncio.wait_for(started.wait(), 1)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertTrue(closed.is_set())

    async def test_weather_result_goes_through_agent_audit_loop(self):
        # Exercise the service with the real weather adapter and an HTTP fixture, without a model bill.
        fixture = agent_fixture.AgentTests()
        gateway = Gateway([[tool_chunk(name='get_weather', arguments='{"city":"武汉"}')],
                           [ModelChunk(content='武汉今日天气'), ModelChunk(done=True, finish_reason='stop')]])
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            events = await fixture.collect(fixture.service(gateway, OpenMeteoWeatherTool(client)))
        self.assertEqual(fixture.tasks.steps[1]['name'], 'get_weather')
        self.assertEqual(fixture.tasks.steps[1]['status'], 'completed')
        result = json.loads(gateway.requests[1][0][-1].content)
        self.assertEqual(result['location']['name'], '武汉')
        self.assertTrue(result['ok'])
        self.assertEqual(events[-1].event, 'done')

    async def test_lifespan_registers_weather_without_tavily_key(self):
        from unittest.mock import Mock, patch
        from pydantic import SecretStr
        from backend.application import create_app, lifespan
        from backend.core.config import AgentSettings, DatabaseSettings, Settings
        app = create_app()
        engine = Mock()
        agent = AgentSettings(tavily_api_key=SecretStr(''))
        with patch('backend.application.Settings.load', return_value=Settings(api_key=SecretStr('mock'))), \
             patch('backend.application.AgentSettings.load', return_value=agent), \
             patch('backend.application.DatabaseSettings.load', return_value=DatabaseSettings(
                 host='unused', username='unused', password=SecretStr('unused'), database='unused')), \
             patch('backend.application.create_database_engine', return_value=engine), \
             patch('backend.application.create_session_factory', return_value=Mock()):
            async with lifespan(app):
                names = [item['function']['name'] for item in app.state.chat_service.tools.definitions()]
                self.assertIn('get_weather', names)
                self.assertTrue(app.state.chat_service.policy.enabled)
        engine.dispose.assert_called_once()
        engine.connect.assert_not_called()
