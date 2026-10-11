import asyncio
import unittest
from unittest.mock import Mock, patch
import httpx
from pydantic import SecretStr
from backend.application import create_app, lifespan
from backend.core.config import AgentSettings, DatabaseSettings, Settings
from backend.domain.agent import ToolError
from backend.tools.public_web import PublicWebTool, SafePageReader

SOGOU = '''<div class="vrwrap"><h3><a href="/link?url=x">武汉<em>新闻</em></a></h3>
<div id="cacheresult_summary_0">今天新闻摘要</div><img src="x"><div data-url="https://example.com/report"></div></div>'''
PAGE = '<html><head><title>报道标题</title><meta property="article:published_time" content="2026-10-11T10:00:00+08:00"></head><body><script>secret_script()</script><nav>导航不要输出</nav><article>' + '新闻正文。' * 100 + '</article></body></html>'
NEWS = '''<rss><channel><item><title>今日报道</title><link>https://example.com/news</link>
<description><![CDATA[<p>新闻摘要</p>]]></description><pubDate>Sun, 11 Oct 2026 02:00:00 GMT</pubDate>
<source url="https://example.com">新闻源</source></item></channel></rss>'''

async def public_resolver(host, port): return ['93.184.216.34']

class PublicWebTests(unittest.IsolatedAsyncioTestCase):
    async def test_news_has_dates_and_summary_without_key(self):
        def handler(request):
            self.assertEqual(request.url.host, 'news.google.com')
            self.assertIn('when:1d', request.url.params['q'])
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, text=NEWS)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await PublicWebTool(client).execute({'query': '时政', 'topic': 'news', 'time_range': 'day'})
        self.assertEqual(result['provider'], 'google_news_rss')
        self.assertEqual(result['sources'][0]['published_date'], '2026-10-11T02:00:00+00:00')
        self.assertEqual(result['sources'][0]['content_type'], 'search_summary')
        self.assertEqual(result['sources'][0]['content'], '新闻摘要')

    async def test_general_search_gets_original_url(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=SOGOU))) as client:
            result = await PublicWebTool(client).execute({'query': '武汉新闻'})
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['sources'][0]['url'], 'https://example.com/report')
        self.assertEqual(result['sources'][0]['content'].strip(), '今天新闻摘要')
        self.assertIsNone(result['sources'][0]['published_date'])

    async def test_read_pins_dns_and_keeps_host_tls_sni(self):
        def handler(request):
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.headers['Host'], 'example.com')
            self.assertEqual(request.extensions['sni_hostname'], 'example.com')
            self.assertNotIn('Authorization', request.headers)
            return httpx.Response(200, headers={'content-type': 'text/html'}, text=PAGE)
        reader = SafePageReader(resolver=public_resolver, transport=httpx.MockTransport(handler))
        async with httpx.AsyncClient() as client:
            result = await PublicWebTool(client, read=True, reader=reader).execute({'url': 'https://example.com/news'})
        source = result['sources'][0]
        self.assertEqual(source['url'], 'https://example.com/news')
        self.assertEqual(source['title'], '报道标题')
        self.assertNotIn('secret_script', source['content'])
        self.assertNotIn('导航不要输出', source['content'])
        self.assertEqual(source['published_date'], '2026-10-11T10:00:00+08:00')

    async def test_literal_private_urls_denied_before_dns(self):
        async def resolver(host, port): self.fail('Private URL resolved')
        reader = SafePageReader(resolver=resolver)
        for url in ('http://127.0.0.1', 'http://169.254.169.254', 'http://localhost', 'file:///etc/passwd',
                    'http://10.0.0.1', 'https://user:pass@example.com', 'http://224.0.0.1', 'http://example.com:8000'):
            with self.subTest(url=url), self.assertRaises(ToolError): await reader.read(url)

    async def test_private_and_mixed_dns_denied_before_fetch(self):
        def handler(request): self.fail('Private DNS fetched')
        for values in (['127.0.0.1'], ['93.184.216.34', '10.0.0.1'], ['::ffff:127.0.0.1'], ['224.0.0.1']):
            async def resolver(host, port): return values
            reader = SafePageReader(resolver=resolver, transport=httpx.MockTransport(handler))
            with self.assertRaises(ToolError) as error: await reader.read('https://example.com')
            self.assertEqual(error.exception.code, 'invalid_url')

    async def test_fake_dns_resolves_public_ip_before_reading(self):
        async def resolver(host, port): return ['198.18.1.130']
        requests = []
        def handler(request):
            requests.append(request.url.host)
            if request.url.host == 'dns.google':
                self.assertEqual(request.url.params['name'], 'example.com')
                return httpx.Response(200, json={'Status': 0, 'Answer': [
                    {'type': 5, 'data': 'cdn.example.com'}, {'type': 1, 'data': '93.184.216.34'}]})
            self.assertEqual(request.url.host, '93.184.216.34')
            self.assertEqual(request.extensions['sni_hostname'], 'example.com')
            return httpx.Response(200, headers={'content-type': 'text/html'}, text=PAGE)
        reader = SafePageReader(resolver=resolver, transport=httpx.MockTransport(handler))
        await reader.read('https://example.com/news')
        self.assertEqual(requests, ['dns.google', '93.184.216.34'])

    async def test_fake_dns_cannot_bypass_private_address_checks(self):
        async def resolver(host, port): return ['198.18.1.130']
        for answer in ('127.0.0.1', '169.254.169.254', '198.18.1.130'):
            def handler(request):
                self.assertEqual(request.url.host, 'dns.google')
                return httpx.Response(200, json={'Status': 0, 'Answer': [{'type': 1, 'data': answer}]})
            reader = SafePageReader(resolver=resolver, transport=httpx.MockTransport(handler))
            with self.assertRaises(ToolError) as error: await reader.read('https://example.com')
            self.assertEqual(error.exception.code, 'invalid_url')

    async def test_private_redirect_and_redirect_dns_denied(self):
        for target in ('http://127.0.0.1/secret', 'https://evil.example.com/secret'):
            requests = []
            async def resolver(host, port): return ['10.0.0.1'] if host == 'evil.example.com' else ['93.184.216.34']
            def handler(request):
                requests.append(request)
                return httpx.Response(302, headers={'location': target})
            reader = SafePageReader(resolver=resolver, transport=httpx.MockTransport(handler))
            with self.assertRaises(ToolError) as error: await reader.read('https://example.com')
            self.assertEqual(error.exception.code, 'invalid_url')
            self.assertEqual(len(requests), 1)

    async def test_cancellation_closes_page(self):
        started, closed = asyncio.Event(), asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                await asyncio.Event().wait()
                yield b'hi'
            async def aclose(self): closed.set()
        reader = SafePageReader(resolver=public_resolver, transport=httpx.MockTransport(
            lambda r: httpx.Response(200, headers={'content-type': 'text/html'}, stream=Body())))
        pending = asyncio.create_task(reader.read('https://example.com'))
        await asyncio.wait_for(started.wait(), 1)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.assertTrue(closed.is_set())

    async def test_xml_entities_and_captcha_not_success(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text='<!DOCTYPE x [<!ENTITY lol "boom">]><rss/>'))) as client:
            with self.assertRaises(ToolError): await PublicWebTool(client).execute({'query': 'news', 'topic': 'news'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text='<html>安全验证</html>'))) as client:
            with self.assertRaises(ToolError): await PublicWebTool(client).execute({'query': 'news'})

    async def test_size_and_content_type_limits(self):
        for content_type, body in (('application/pdf', b'data'), ('text/html', b'A' * (1024 * 1024 + 1))):
            reader = SafePageReader(resolver=public_resolver, transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={'content-type': content_type}, content=body)))
            with self.assertRaises(ToolError): await reader.read('https://example.com')

    async def test_lifespan_selects_provider_from_key_and_setting(self):
        from backend.tools.web import TavilyTool
        for provider, key, expected in (('auto', '', PublicWebTool), ('public', 'mock', PublicWebTool),
                                       ('auto', 'mock', TavilyTool), ('tavily', '', TavilyTool)):
            engine = Mock()
            with patch('backend.application.Settings.load', return_value=Settings(api_key=SecretStr('mock'))), \
                 patch('backend.application.AgentSettings.load', return_value=AgentSettings(web_provider=provider, tavily_api_key=SecretStr(key))), \
                 patch('backend.application.DatabaseSettings.load', return_value=DatabaseSettings(
                     host='unused', username='unused', password=SecretStr('unused'), database='unused')), \
                 patch('backend.application.create_database_engine', return_value=engine), \
                 patch('backend.application.create_session_factory', return_value=Mock()):
                app = create_app()
                async with lifespan(app):
                    self.assertIsInstance(app.state.chat_service.tools.tools['web_search'], expected)
                    self.assertIsInstance(app.state.chat_service.tools.tools['web_read'], expected)
            engine.connect.assert_not_called()
