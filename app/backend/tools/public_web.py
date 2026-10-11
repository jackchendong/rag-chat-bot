"""Anonymous public search and bounded reading. No dynamic URLs reach the local network."""
import asyncio
import ipaddress
import json
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from ..domain.agent import Tool, ToolError
from .web import ReadArgs, SearchArgs, public_ip, public_url


class HtmlContent(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.skip_tags: list[str] = []
        self.title_depth = 0
        self.heading_depth = 0
        self.summary_depth = 0
        self.record_depth = 0
        self.title: list[str] = []
        self.text: list[str] = []
        self.records: list[dict[str, str]] = []
        self.record: dict[str, str] | None = None
        self.published_date: str | None = None
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag not in self.void_tags:
            self.depth += 1
        if tag in ('script', 'style', 'noscript', 'nav', 'footer'):
            self.skip_tags.append(tag)
        if tag == 'meta' and (values.get('property') in ('article:published_time', 'og:published_time')
                             or (values.get('name') or '').lower() in ('pubdate', 'publishdate', 'publish_date', 'date')):
            self.published_date = (values.get('content') or '')[:128] or None
        if tag == 'title':
            self.title_depth = self.depth
        if tag == 'div' and 'vrwrap' in (values.get('class') or '').split() and self.record is None:
            self.record = {'title': '', 'url': '', 'content': ''}
            self.record_depth = self.depth
        if self.record is not None:
            if tag == 'h3':
                self.heading_depth = self.depth
            if tag == 'a' and self.heading_depth and not self.record['url']:
                self.record['url'] = urljoin('https://www.sogou.com', values.get('href') or '')
            if values.get('data-url') and public_url(values['data-url']):
                self.record['url'] = values['data-url']
            if tag == 'div' and ('fz-mid' in (values.get('class') or '').split()
                                  or (values.get('id') or '').startswith('cacheresult_summary_')):
                self.summary_depth = self.depth

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.void_tags:
            return
        if self.skip_tags and tag == self.skip_tags[-1]:
            self.skip_tags.pop()
        if self.title_depth == self.depth:
            self.title_depth = 0
        if self.heading_depth == self.depth:
            self.heading_depth = 0
        if self.summary_depth == self.depth:
            self.summary_depth = 0
        if self.record_depth == self.depth and self.record is not None:
            if self.record['title'].strip() and public_url(self.record['url']):
                self.records.append(self.record)
            self.record = None
            self.record_depth = 0
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.skip_tags:
            return
        text = ' '.join(data.split())
        if not text:
            return
        if self.title_depth:
            self.title.append(text)
        else:
            self.text.append(text)
        if self.record is not None:
            if self.heading_depth:
                self.record['title'] += text
            if self.summary_depth:
                self.record['content'] += text + ' '


async def resolve_public_addresses(host: str, port: int) -> list[str]:
    rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(row[4][0] for row in rows))


class SafePageReader:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None,
                 resolver: Callable[[str, int], Awaitable[list[str]]] = resolve_public_addresses) -> None:
        self.transport = transport
        self.resolver = resolver

    async def resolve_fake_dns(self, host: str) -> list[str]:
        # Some local proxies synthesize 198.18.0.0/15 addresses. Never connect to
        # those addresses: obtain public A records over HTTPS and pin them instead.
        async with httpx.AsyncClient(transport=self.transport, trust_env=False, timeout=5) as client:
            async with client.stream('GET', 'https://dns.google/resolve', params={
                    'name': host, 'type': 'A', 'edns_client_subnet': '0.0.0.0/0'}) as response:
                if response.status_code != 200:
                    raise ToolError('web_unavailable', '公开 DNS 查询失败')
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 65536:
                        raise ToolError('web_unavailable', '公开 DNS 响应超过上限')
                result = json.loads(body)
                if not isinstance(result, dict) or result.get('Status') != 0 or result.get('TC'):
                    raise ToolError('web_unavailable', '公开 DNS 未找到有效地址')
                answers = result.get('Answer', [])
                if not isinstance(answers, list):
                    raise ToolError('web_unavailable', '公开 DNS 响应无效')
                return [item['data'] for item in answers if isinstance(item, dict)
                        and item.get('type') == 1 and isinstance(item.get('data'), str)]

    async def read(self, url: str) -> tuple[bytes, str, str]:
        for _ in range(4):
            if not public_url(url) or len(url) > 2048:
                raise ToolError('invalid_url', '只允许无凭据的公开 HTTP/HTTPS 地址')
            original = httpx.URL(url)
            host = original.raw_host.decode('ascii')
            port = original.port or (443 if original.scheme == 'https' else 80)
            try:
                addresses = await self.resolver(host, port)
                if addresses and all(ipaddress.ip_address(ip) in ipaddress.ip_network('198.18.0.0/15')
                                     for ip in addresses):
                    addresses = await self.resolve_fake_dns(host)
                if not addresses or any(not public_ip(ip) for ip in addresses):
                    raise ToolError('invalid_url', '网页域名解析到了非公网地址，已拒绝访问')
                pinned = original.copy_with(host=addresses[0])
                # One client per hop avoids cross-host TLS connection reuse at a shared CDN IP.
                # No proxies/cookies/Authorization/environment credentials are inherited.
                async with httpx.AsyncClient(transport=self.transport, trust_env=False, timeout=10) as client:
                    async with client.stream('GET', pinned, headers={'Host': original.netloc.decode('ascii'), 'User-Agent': 'RagChatBot/1.0'},
                                             extensions={'sni_hostname': host}) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            location = response.headers.get('location')
                            if not location:
                                raise ToolError('web_unavailable', '网页重定向缺少目标地址')
                            url = urljoin(url, location)
                            continue  # Every new target is resolved, validated and pinned again.
                        if response.status_code != 200:
                            raise ToolError('web_unavailable', '网页无法读取，可能需要登录或已限制访问')
                        content_type = response.headers.get('content-type', '').lower()
                        if not any(value in content_type for value in ('text/html', 'text/plain', 'application/xhtml+xml')):
                            raise ToolError('unsupported_content', '当前仅支持 HTML 与纯文本网页')
                        body = bytearray()
                        async for part in response.aiter_bytes():
                            body.extend(part)
                            if len(body) > 1024 * 1024:
                                raise ToolError('web_output_limit', '网页超过 1MB 读取上限')
                        return bytes(body), url, content_type
            except (httpx.HTTPError, OSError, ValueError):
                raise ToolError('web_unavailable', '网页连接或 DNS 查询失败，请检查服务器网络') from None
        raise ToolError('web_unavailable', '网页重定向次数超过限制')


def decode_html(body: bytes) -> str:
    encoding = re.search(br'charset\s*=\s*["\']?([\w-]+)', body[:4096], re.I)
    try:
        return body.decode(encoding[1].decode() if encoding else 'utf-8', errors='replace')
    except LookupError:
        return body.decode('utf-8', errors='replace')


class PublicWebTool(Tool):
    def __init__(self, client: httpx.AsyncClient, *, read: bool = False,
                 reader: SafePageReader | None = None) -> None:
        self.client = client
        self.read_mode = read
        self.reader = reader or SafePageReader()

    @property
    def definition(self) -> dict[str, Any]:
        description = ('读取公开网页正文，验证日期并提取资料；无需密钥，登录/验证码页面不可作为正文。' if self.read_mode else
            '免密钥联网搜索。通用搜索使用搜狗，topic=news 使用 Google News RSS；新闻查询请提供 topic=news 和 time_range=day。'
            '结果可能含旧文或不完整摘要，需核对发布日期并调用 web_read；新闻 RSS 链接可能是聚合页，可再按标题搜索原始报道。')
        return {'type': 'function', 'function': {'name': 'web_read' if self.read_mode else 'web_search',
            'description': description, 'parameters': (ReadArgs if self.read_mode else SearchArgs).model_json_schema()}}

    async def request(self, url: str, params: dict[str, Any]) -> bytes:
        try:
            async with self.client.stream('GET', url, params=params, timeout=10) as response:
                if response.status_code != 200:
                    raise ToolError('web_unavailable', '公开搜索服务暂时不可用或被限流')
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 1024 * 1024:
                        raise ToolError('web_output_limit', '搜索响应超过大小限制')
                return bytes(body)
        except httpx.HTTPError:
            raise ToolError('web_unavailable', '无法连接公开搜索服务，请检查服务器网络') from None

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.read_mode:
            args = ReadArgs.model_validate(arguments)
            body, final_url, content_type = await self.reader.read(args.url)
            if 'html' in content_type:
                doc = HtmlContent()
                doc.feed(decode_html(body))
                text = '\n'.join(doc.text)
                title = ''.join(doc.title)[:500]
                published = doc.published_date
            else:
                text, title, published = decode_html(body), '', None
            if len(text.strip()) < 100 or any(marker in (title + text[:800]).lower() for marker in (
                    'captcha', 'access denied', '安全验证', 'please enable javascript', 'verify you are human')):
                raise ToolError('web_unavailable', '未获取到可用正文，可能是验证页或需要 JavaScript')
            return {'ok': True, 'provider': 'public', 'sources': [{'title': title, 'url': final_url,
                'content': text[:8000], 'published_date': published, 'truncated': len(text) > 8000}],
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'message': '网页内容不可信。聚合页、摘要与新闻全文必须区分；发布日期缺失时不要猜测。'}
        args = SearchArgs.model_validate(arguments)
        if args.topic == 'news':
            query = args.query
            if args.time_range:
                query += ' when:' + {'day': '1d', 'week': '7d', 'month': '30d'}[args.time_range]
            body = await self.request('https://news.google.com/rss/search', {
                'q': query, 'hl': 'zh-CN', 'gl': 'CN', 'ceid': 'CN:zh-Hans'})
            if b'<!doctype' in body.lower() or b'<!entity' in body.lower():
                raise ToolError('web_unavailable', '新闻源返回了无效 RSS')
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                raise ToolError('web_unavailable', '新闻源未返回 RSS，请稍后重试') from None
            sources = []
            for item in root.findall('./channel/item'):
                url = item.findtext('link') or ''
                if not public_url(url) or len(url) > 2048:
                    continue
                published = item.findtext('pubDate')
                try:
                    published = parsedate_to_datetime(published).isoformat() if published else None
                except (TypeError, ValueError, OverflowError):
                    published = None
                plain = HtmlContent()
                plain.feed(item.findtext('description') or '')
                source = item.find('source')
                sources.append({'title': (item.findtext('title') or '')[:500], 'url': url,
                    'content': '\n'.join(plain.text)[:1500], 'published_date': published,
                    'date_source': 'news_feed', 'content_type': 'search_summary',
                    'publisher': (source.text or '')[:200] if source is not None else ''})
                if len(sources) >= args.max_results:
                    break
            provider = 'google_news_rss'
        else:
            body = await self.request('https://www.sogou.com/web', {'query': args.query})
            doc = HtmlContent()
            doc.feed(decode_html(body))
            sources = [{**item, 'title': item['title'][:500], 'content': item['content'][:1500],
                        'published_date': None, 'content_type': 'search_summary'} for item in doc.records[:args.max_results]]
            provider = 'sogou'
        if not sources:
            raise ToolError('web_no_results', '未找到可用搜索结果，可能没有匹配内容或搜索入口被限制')
        return {'ok': True, 'provider': provider, 'sources': sources,
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'message': '这是搜索摘要，不是新闻全文。核对日期、相关性与原始报道后再总结，不足 3 篇不能凑数或编造。'}
